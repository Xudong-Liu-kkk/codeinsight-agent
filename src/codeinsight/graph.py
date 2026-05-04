"""LangGraph 多步自主分析图。

在现有 create_agent 的 ReAct 能力之上，加入 Planner（任务拆解）、
Reviewer（自我验证）和 Synthesizer（汇总）三个节点，
让 Agent 能自主推进复杂分析任务。
"""

from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

# 安全上限：最多循环迭代次数。
MAX_ITERATIONS = 3

# —— 节点提示词 ——

PLANNER_PROMPT = """你是任务规划器。分析用户问题并拆解为具体的子任务。

规则：
- 简单问题（一句话可答）→ 1 个子任务
- 中等复杂（需要搜索并读取代码）→ 2~3 个子任务
- 复杂问题（需多维度分析）→ 3~5 个子任务
- 每个子任务描述必须具体可执行

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


# —— 图状态 ——

class AskState(TypedDict):
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
    START → planner → executor → (还有步骤? → executor | reviewer)
    reviewer → (sufficient? → synthesizer | 回到 executor)
    synthesizer → END
    """

    def _planner(state: AskState) -> dict:
        question = str(state["messages"][0].content if state["messages"] else "")
        if not question:
            return {"plan_steps": ["分析项目"], "current_step": 0, "findings": [], "iteration": 0, "is_sufficient": "NO", "final_answer": ""}

        response = chat_model.invoke([
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"问题：{question}"),
        ])
        try:
            import json
            import re

            text = str(response.content or "")
            json_match = re.search(r"\{[\s\S]*\}", text)
            plan_data = json.loads(json_match.group() if json_match else text)
            steps = plan_data.get("steps", [question])
        except Exception:
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

    def _executor(state: AskState) -> dict:
        idx = state.get("current_step", 0)
        steps = state.get("plan_steps", [])
        if idx >= len(steps):
            return {"current_step": idx + 1}

        step_desc = steps[idx]
        task_msg = HumanMessage(
            content=(
                f"执行子任务（{idx + 1}/{len(steps)}）：{step_desc}\n\n"
                f"原始用户问题：{state.get('question', '')}\n"
                f"请用工具完成此子任务，然后简要总结发现。"
            ),
        )

        # 复用现有的 create_agent 作为子任务的执行循环。
        step_agent = create_agent(
            model=chat_model,
            tools=tools,
            system_prompt=EXECUTOR_PROMPT + "\n" + memory_context if memory_context else EXECUTOR_PROMPT,
        )
        result = step_agent.invoke({"messages": [task_msg]})
        msgs = result.get("messages", [])
        answer = ""
        for msg in reversed(msgs):
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
        response = chat_model.invoke([
            SystemMessage(content=REVIEWER_PROMPT),
            HumanMessage(content=f"用户问题：{question}\n\n已收集信息：\n{all_findings}"),
        ])
        reply = str(response.content or "")
        is_sufficient = "YES" if reply.strip().upper().startswith("YES") else "NO"
        return {"is_sufficient": is_sufficient, "iteration": state.get("iteration", 0) + 1}

    def _synthesizer(state: AskState) -> dict:
        all_findings = "\n\n".join(state.get("findings", []))
        question = state.get("question", "")
        response = chat_model.invoke([
            SystemMessage(content=SYNTHESIZER_PROMPT),
            HumanMessage(content=f"用户问题：{question}\n\n各步骤分析发现：\n{all_findings}"),
        ])
        return {"final_answer": str(response.content or "")}

    # 路由函数。
    def _route_after_executor(state: AskState) -> str:
        if state.get("current_step", 0) < len(state.get("plan_steps", [])):
            return "executor"
        return "reviewer"

    def _route_after_reviewer(state: AskState) -> str:
        if state.get("is_sufficient", "NO") == "YES":
            return "synthesizer"
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "synthesizer"
        # 信息不足，追加一个补充步骤后继续。
        steps = list(state.get("plan_steps", []))
        steps.append("补充遗漏信息并完善分析")
        return "executor"

    graph = StateGraph(AskState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("reviewer", _reviewer)
    graph.add_node("synthesizer", _synthesizer)

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

    return graph.compile()
