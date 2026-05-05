"""LangGraph 多 Agent 协作分析图。

将 Planner、Reader、Reviewer、Synthesizer 四个角色实现为四个独立的
create_agent 子 Agent，每个 Agent 有自己专属的 system prompt 和工具集。
通过父 StateGraph 编排协作流程，Agent 之间通过共享 state 传递分析结果。

  START → Planner Agent → Reader Agent → (还有步骤? → Reader Agent)
                        ↓ 全部完成
                     Reviewer Agent → (充分? → Synthesizer Agent → END)
                         ↓ 不充分，回到 Reader（最多 3 轮）

Planner Agent     — 无工具，纯推理，输出 JSON 任务计划。
Reader Agent      — 有 read/search/overview/diagnose/deps 全工具集。
Reviewer Agent    — 无工具，纯评估，判断信息充分性。
Synthesizer Agent — 无工具，汇总生成结构化最终回答。
"""

import sys
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

MAX_ITERATIONS = 3

# —— Agent Prompt ——

PLANNER_PROMPT = """你是 Planner Agent，负责分析用户问题并拆解为具体的子任务。

规则：
- 简单问题（一句话可答）→ 1 个子任务
- 中等复杂（需要搜索并读取代码）→ 2~3 个子任务
- 复杂问题（需多维度分析）→ 3~5 个子任务
- 每个子任务描述必须具体可执行，如"搜索 try/except 的使用位置"，而非"分析代码"

仅返回 JSON（不要 markdown 代码块），格式：
{"steps": ["子任务1描述", "子任务2描述"]}"""

READER_PROMPT = """你是 Reader Agent，负责执行代码分析子任务。
你可以调用工具搜索、读取代码文件，然后汇总发现。
完成后用中文给出本步骤的总结。"""

REVIEWER_PROMPT = """你是 Reviewer Agent，负责判断已收集的信息是否足够。
仅回答 YES（信息充分，可以汇总）或 NO（信息不足）。
如果回答 NO，请在第二行简要说明还缺什么。"""

SYNTHESIZER_PROMPT = """你是 Synthesizer Agent，负责汇总所有分析发现生成最终回答。

格式要求：
## 结论
（核心发现，1~3 句话）

## 依据
（引用分析发现中的具体证据）

## 建议
（可执行的下一步行动）

不要编造未在分析发现中出现的信息。"""


# —— 图状态 ——

class AskState(TypedDict):
    """多 Agent 协作图的状态。

    messages 使用 add_messages reducer 累积全对话历史，
    其余字段由各 Agent 节点的包装函数在父图中管理。
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
    """构建多 Agent 协作 LangGraph 图。

    创建四个独立的 Agent 实例，每个有专属的 prompt 和工具集：
      - Planner Agent：无工具，负责拆解任务
      - Reader Agent：有完整工具集，负责执行代码分析
      - Reviewer Agent：无工具，负责审查信息充分性
      - Synthesizer Agent：无工具，负责汇总生成回答

    Args:
        chat_model: LangChain ChatOpenAI 实例。
        tools: Agent 可用工具列表（只给 Reader Agent）。
        memory_context: 项目长期记忆上下文（注入 Reader Agent）。
    """

    # —— 创建四个独立 Agent 实例 ——
    # 每个 Agent 是 create_agent 返回的 CompiledStateGraph，
    # 有自己的 system prompt、工具集和 ReAct 循环。

    planner_agent = create_agent(
        model=chat_model, tools=[], system_prompt=PLANNER_PROMPT,
    )
    reader_agent = create_agent(
        model=chat_model, tools=tools,
        system_prompt=READER_PROMPT + "\n" + memory_context if memory_context else READER_PROMPT,
    )
    reviewer_agent = create_agent(
        model=chat_model, tools=[], system_prompt=REVIEWER_PROMPT,
    )
    synthesizer_agent = create_agent(
        model=chat_model, tools=[], system_prompt=SYNTHESIZER_PROMPT,
    )

    # —— 父图节点（包装 Agent 调用）——
    # 每个节点调用对应 Agent，并从 Agent 输出中提取信息写入父图 state。

    def _planner(state: AskState) -> dict:
        question = str(state["messages"][0].content if state["messages"] else "")
        if not question:
            return {
                "plan_steps": ["分析项目"], "current_step": 0,
                "findings": [], "iteration": 0, "is_sufficient": "NO", "final_answer": "",
            }

        result = planner_agent.invoke({
            "messages": [HumanMessage(content=f"问题：{question}")],
        })
        msgs = result.get("messages", [])
        reply = ""
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and msg.content:
                reply = str(msg.content)
                break

        try:
            import json, re
            json_match = re.search(r"\{[\s\S]*\}", reply)
            plan_data = json.loads(json_match.group() if json_match else reply)
            steps = plan_data.get("steps", [question])
        except Exception:
            steps = [question]

        return {
            "question": question, "plan_steps": steps, "current_step": 0,
            "findings": [], "iteration": 0, "is_sufficient": "NO", "final_answer": "",
        }

    def _executor(state: AskState) -> dict:
        idx = state.get("current_step", 0)
        steps = state.get("plan_steps", [])
        if idx >= len(steps):
            return {"current_step": idx + 1}

        step_desc = steps[idx]
        task_msg = HumanMessage(content=(
            f"执行子任务（{idx + 1}/{len(steps)}）：{step_desc}\n\n"
            f"原始用户问题：{state.get('question', '')}\n"
            f"请用工具完成此子任务，然后简要总结发现。"
        ))

        # Reader Agent 流式执行，逐 token 输出。
        final_messages: list = []
        pending_tool_names: set = set()
        for event in reader_agent.stream(
            {"messages": [task_msg]},
            stream_mode=["messages", "updates"],
        ):
            mode, data = event
            if mode == "messages":
                msg, _metadata = data
                content = getattr(msg, "content", None)
                tool_call_chunks = getattr(msg, "tool_call_chunks", []) if hasattr(msg, "tool_call_chunks") else []
                for tc in tool_call_chunks:
                    tc_name = getattr(tc, "name", None)
                    if tc_name and tc_name not in pending_tool_names:
                        pending_tool_names.add(tc_name)
                        print(f"\n  → 调用工具：{tc_name}", file=sys.stderr, flush=True)
                if content:
                    print(content, end="", file=sys.stderr, flush=True)
                if isinstance(msg, ToolMessage):
                    print(f" → {str(msg.content)[:100]}", file=sys.stderr, flush=True)
            elif mode == "updates":
                for _node_name, output in data.items():
                    msgs = output.get("messages", [])
                    final_messages.extend(msgs)

        print(file=sys.stderr, flush=True)

        answer = ""
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                answer = str(msg.content)
                break
        if not answer:
            answer = "此步骤未获取到有效信息。"

        findings = list(state.get("findings", []))
        findings.append(f"[步骤 {idx + 1}] {step_desc}\n{answer}")
        return {"findings": findings, "current_step": idx + 1}

    def _reviewer(state: AskState) -> dict:
        all_findings = "\n\n".join(state.get("findings", []))
        question = state.get("question", "")
        result = reviewer_agent.invoke({
            "messages": [HumanMessage(content=f"用户问题：{question}\n\n已收集信息：\n{all_findings}")],
        })
        msgs = result.get("messages", [])
        reply = ""
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and msg.content:
                reply = str(msg.content)
                break
        is_sufficient = "YES" if reply.strip().upper().startswith("YES") else "NO"
        return {"is_sufficient": is_sufficient, "iteration": state.get("iteration", 0) + 1}

    def _synthesizer(state: AskState) -> dict:
        all_findings = "\n\n".join(state.get("findings", []))
        question = state.get("question", "")
        result = synthesizer_agent.invoke({
            "messages": [HumanMessage(content=f"用户问题：{question}\n\n各步骤分析发现：\n{all_findings}")],
        })
        msgs = result.get("messages", [])
        reply = ""
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and msg.content:
                reply = str(msg.content)
                break
        return {"final_answer": reply}

    # —— 路由 ——

    def _route_after_executor(state: AskState) -> str:
        if state.get("current_step", 0) < len(state.get("plan_steps", [])):
            return "executor"
        return "reviewer"

    def _route_after_reviewer(state: AskState) -> str:
        if state.get("is_sufficient", "NO") == "YES":
            return "synthesizer"
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "synthesizer"
        steps = list(state.get("plan_steps", []))
        steps.append("补充遗漏信息并完善分析")
        state["plan_steps"] = steps
        return "executor"

    # —— 装配 ——
    graph = StateGraph(AskState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("reviewer", _reviewer)
    graph.add_node("synthesizer", _synthesizer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges("executor", _route_after_executor, {
        "executor": "executor", "reviewer": "reviewer",
    })
    graph.add_conditional_edges("reviewer", _route_after_reviewer, {
        "executor": "executor", "synthesizer": "synthesizer",
    })
    graph.add_edge("synthesizer", END)

    return graph.compile()
