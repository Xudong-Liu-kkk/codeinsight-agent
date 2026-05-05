"""LangGraph 多步自主分析图。

在 LangChain 原生 `create_agent` 的 ReAct 循环之上，加入三个节点构成
完整的自主分析闭环：

  START → Planner → Executor → Reviewer → (通过? → Synthesizer → END)
                ↑         ↑         ↓ 不通过，回到 Executor（最多 3 轮）
                └─────────┴─────────┘

Planner    — 分析用户问题，拆解为具体可执行的子任务列表（JSON 输出）。
Executor   — 逐个执行子任务，内部复用 create_agent 实现工具调用循环。
Reviewer   — 检查已收集的信息是否充分，不足时追加补充步骤。
Synthesizer— 汇总所有步骤的发现，生成结构化最终回答。

图状态 AskState 通过 add_messages reducer 累积对话历史，
findings 列表在 Executor 中逐步追加，确保每一步的分析发现都可追溯。
"""

import sys
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

# 安全上限：Reviewer 最多允许循环的轮数，防止无限执行或 token 耗尽。
MAX_ITERATIONS = 3

# —— 各节点 System Prompt ——
# 每个 Prompt 只描述该节点的单一职责，不做额外推理，保持专注。

PLANNER_PROMPT = """你是任务规划器。分析用户问题并拆解为具体的子任务。

规则：
- 简单问题（一句话可答）→ 1 个子任务
- 中等复杂（需要搜索并读取代码）→ 2~3 个子任务
- 复杂问题（需多维度分析）→ 3~5 个子任务
- 每个子任务描述必须具体可执行，如"搜索 try/except 的使用位置"，而非"分析代码"

仅返回 JSON（不要 markdown 代码块），格式：
{"steps": ["子任务1描述", "子任务2描述"]}"""

EXECUTOR_PROMPT = """你是执行器。完成当前子任务，必要时调用工具收集信息。
完成后用中文给出本步骤的总结发现。"""

REVIEWER_PROMPT = """你是信息审查器。判断已收集的信息是否足够回答用户问题。
仅回答 YES（信息充分，可以汇总）或 NO（信息不足）。
如果回答 NO，请在第二行简要说明还缺什么（一行中文）。"""

SYNTHESIZER_PROMPT = """你是综合回答器。基于所有分析发现生成最终中文回答。

格式要求：
## 结论
（核心发现，1~3 句话）

## 依据
（引用分析发现中的具体证据）

## 建议
（可执行的下一步行动）

不要编造未在分析发现中出现的信息。"""


# —— 图状态定义 ——
# AskState 是在图中各节点间流转的共享状态对象。
# Annotated[list, add_messages] 表示 messages 字段使用 LangGraph 的
# add_messages reducer，新消息会追加到历史而非替换。

class AskState(TypedDict):
    """多步分析图的状态。

    Attributes:
        messages: 完整的对话消息历史（含工具调用），使用 add_messages reducer 累积。
        question: 用户原始问题文本。
        plan_steps: Planner 拆解出的子任务描述列表。
        current_step: 当前正在执行的子任务索引（从 0 开始）。
        findings: 已完成的各步骤发现文本列表，Executor 每完成一步追加一条。
        iteration: Reviewer 已审查的次数，用于安全上限控制。
        is_sufficient: Reviewer 的判决结果，"YES" 或 "NO"。
        final_answer: Synthesizer 生成的最终回答文本。
    """

    messages: Annotated[list, add_messages]
    question: str
    plan_steps: list[str]
    current_step: int
    findings: list[str]
    iteration: int
    is_sufficient: str
    final_answer: str


# —— 图构建 ——

def build_ask_graph(chat_model, tools, memory_context: str = ""):
    """构建多步自主分析的 LangGraph 图。

    图结构：
    START → planner → executor ──(还有步骤?)──→ executor（循环）
                     executor ──(全部完成)──→ reviewer
                     reviewer ──(信息不足)──→ executor（追加新步骤）
                     reviewer ──(信息充分 或 达到上限)──→ synthesizer → END

    Executor 节点内部通过 LangChain 的 create_agent 实现完整的 ReAct
    工具调用循环，因此每个子任务的执行本身也是一个 agent 调用。

    Args:
        chat_model: LangChain ChatOpenAI 实例，用于所有 LLM 调用。
        tools: Agent 可用的工具列表。
        memory_context: 项目长期记忆上下文字符串，注入 Executor 的 prompt。
    """

    # ———— Planner 节点 ————
    # 职责：分析用户问题，生成子任务 JSON 计划。
    # 输入：AskState.messages 中第一条 HumanMessage（用户原始问题）。
    # 输出：plan_steps（子任务列表）、question、初始化计数器。

    def _planner(state: AskState) -> dict:
        question = str(state["messages"][0].content if state["messages"] else "")
        if not question:
            return {
                "plan_steps": ["分析项目"],
                "current_step": 0,
                "findings": [],
                "iteration": 0,
                "is_sufficient": "NO",
                "final_answer": "",
            }

        # 调用 LLM 生成计划，期望返回 JSON。
        response = chat_model.invoke([
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"问题：{question}"),
        ])
        try:
            import json
            import re

            text = str(response.content or "")
            # 容错：提取文本中第一个 JSON 对象，忽略前后的 markdown 包裹。
            json_match = re.search(r"\{[\s\S]*\}", text)
            plan_data = json.loads(json_match.group() if json_match else text)
            steps = plan_data.get("steps", [question])
        except Exception:
            # JSON 解析失败时，将原问题本身作为唯一的子任务。
            steps = [question]

        return {
            "question": question,
            "plan_steps": steps,
            "current_step": 0,
            "findings": [],
            "iteration": 0,
            "is_sufficient": "NO",
            "final_answer": "",
        }

    # ———— Executor 节点 ————
    # 职责：执行当前索引的子任务。内部用 create_agent 实现工具调用。
    # 输入：plan_steps[current_step] 是当前任务描述。
    # 输出：findings 追加一项 "[步骤 N] 任务描述\n{执行结果}"。

    def _executor(state: AskState) -> dict:
        idx = state.get("current_step", 0)
        steps = state.get("plan_steps", [])
        if idx >= len(steps):
            return {"current_step": idx + 1}

        step_desc = steps[idx]
        # 构造子任务消息，包含原始问题上下文。
        task_msg = HumanMessage(
            content=(
                f"执行子任务（{idx + 1}/{len(steps)}）：{step_desc}\n\n"
                f"原始用户问题：{state.get('question', '')}\n"
                f"请用工具完成此子任务，然后简要总结发现。"
            ),
        )

        # 用 create_agent 构建 ReAct 循环，通过 stream 逐 token 输出。
        step_agent = create_agent(
            model=chat_model,
            tools=tools,
            system_prompt=EXECUTOR_PROMPT + "\n" + memory_context if memory_context else EXECUTOR_PROMPT,
        )

        # 流式执行子任务：逐 token 输出到 stderr，同时累积完整结果。
        # create_agent 的 stream 格式：messages mode → (mode, (msg, metadata))
        final_messages: list = []
        pending_tool_names: set = set()
        for event in step_agent.stream(
            {"messages": [task_msg]},
            stream_mode=["messages", "updates"],
        ):
            mode, data = event

            if mode == "messages":
                # messages 模式下 data 是 (message, metadata) 元组。
                msg, _metadata = data

                # —— 逐 token 流式输出 ——
                content = getattr(msg, "content", None)
                tool_call_chunks = getattr(msg, "tool_call_chunks", []) if hasattr(msg, "tool_call_chunks") else []

                # 工具调用摘要（首次出现时输出工具名）。
                for tc in tool_call_chunks:
                    tc_name = getattr(tc, "name", None)
                    if tc_name and tc_name not in pending_tool_names:
                        pending_tool_names.add(tc_name)
                        print(f"\n  → 调用工具：{tc_name}", file=sys.stderr, flush=True)

                # LLM 逐 token 输出。
                if content:
                    print(content, end="", file=sys.stderr, flush=True)

                # 工具返回结果摘要。
                if isinstance(msg, ToolMessage):
                    result_preview = str(msg.content)[:100]
                    print(f" → {result_preview}", file=sys.stderr, flush=True)

            elif mode == "updates":
                # —— 累积消息状态 ——
                for _node_name, output in data.items():
                    msgs = output.get("messages", [])
                    final_messages.extend(msgs)

        print(file=sys.stderr, flush=True)  # 换行

        # 提取最终回答。
        answer = ""
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                answer = str(msg.content)
                break
        if not answer:
            answer = "此步骤未获取到有效信息。"

        # 追加本步骤发现到共享状态。
        findings = list(state.get("findings", []))
        findings.append(f"[步骤 {idx + 1}] {step_desc}\n{answer}")

        return {"findings": findings, "current_step": idx + 1}

    # ———— Reviewer 节点 ————
    # 职责：审查已收集的全部发现，判断是否足以回答用户问题。
    # 输入：findings（所有已完成步骤的发现）、question（原始问题）。
    # 输出：is_sufficient（"YES"/"NO"）、iteration 自增。

    def _reviewer(state: AskState) -> dict:
        all_findings = "\n\n".join(state.get("findings", []))
        question = state.get("question", "")
        response = chat_model.invoke([
            SystemMessage(content=REVIEWER_PROMPT),
            HumanMessage(content=f"用户问题：{question}\n\n已收集信息：\n{all_findings}"),
        ])
        reply = str(response.content or "")
        # 判定：以 "YES" 开头即为充分，其余视为不充分。
        is_sufficient = "YES" if reply.strip().upper().startswith("YES") else "NO"
        return {"is_sufficient": is_sufficient, "iteration": state.get("iteration", 0) + 1}

    # ———— Synthesizer 节点 ————
    # 职责：汇总所有步骤发现，生成结构化的最终中文回答。
    # 输入：findings、question。
    # 输出：final_answer。

    def _synthesizer(state: AskState) -> dict:
        all_findings = "\n\n".join(state.get("findings", []))
        question = state.get("question", "")
        response = chat_model.invoke([
            SystemMessage(content=SYNTHESIZER_PROMPT),
            HumanMessage(content=f"用户问题：{question}\n\n各步骤分析发现：\n{all_findings}"),
        ])
        return {"final_answer": str(response.content or "")}

    # ———— 路由函数 ————
    # 以下两个函数决定图的控制流方向。

    def _route_after_executor(state: AskState) -> str:
        """Executor 执行后的路由。
        当前步骤小于总步骤数 → 继续 Executor；
        否则 → 进入 Reviewer。
        """
        if state.get("current_step", 0) < len(state.get("plan_steps", [])):
            return "executor"
        return "reviewer"

    def _route_after_reviewer(state: AskState) -> str:
        """Reviewer 审查后的路由。
        信息充分 或 达到迭代上限 → Synthesizer；
        信息不足且未达上限 → 追加补充步骤，回到 Executor。
        """
        if state.get("is_sufficient", "NO") == "YES":
            return "synthesizer"
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "synthesizer"
        # 信息不足：在 plan_steps 末尾追加一个补充步骤。
        steps = list(state.get("plan_steps", []))
        steps.append("补充遗漏信息并完善分析")
        state["plan_steps"] = steps
        return "executor"

    # ———— 图装配 ————
    graph = StateGraph(AskState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("reviewer", _reviewer)
    graph.add_node("synthesizer", _synthesizer)

    # 边定义：
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges("executor", _route_after_executor, {
        "executor": "executor",
        "reviewer": "reviewer",
    })
    graph.add_conditional_edges("reviewer", _route_after_reviewer, {
        "executor": "executor",
        "synthesizer": "synthesizer",
    })
    graph.add_edge("synthesizer", END)

    # 编译为可执行的 CompiledStateGraph。
    return graph.compile()
