"""CodeInsight Agent 编排层。

本模块提供 ask（自然语言问答）和 review（代码审查）两个 Agent 入口，
底层通过 LangChain 框架调用只读工具并由大模型生成回答。
"""

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from codeinsight.agent_tools import _report_to_text, create_tools
from codeinsight.engine import run_read
from codeinsight.graph import build_ask_graph
from codeinsight.llm import LLMConfigError, create_langchain_chat_model
from codeinsight.memory import ProjectMemory
from codeinsight.schemas import AnalysisReport, Finding

# —— 提示词 ——

REVIEW_SYSTEM_PROMPT = (
    "你是 CodeInsight Agent 的只读代码审查助手。"
    "你只能审查和解释代码，不能声称已经修改代码。"
    "回答必须使用中文，并按照：总体评价、主要风险、改进建议、可选后续检查 的结构输出。"
    "请关注正确性、异常处理、安全边界、可维护性、复杂度和测试覆盖。"
)


# —— ask 命令 ——

def run_ask(root: str, question: str, provider: str | None = None) -> AnalysisReport:
    """运行自然语言 ask Agent。

    大模型通过 LangChain Agent 自主决定调用哪些只读工具，
    基于工具返回的真实代码上下文生成中文分析回答。
    """
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"ask 失败：项目根目录不存在：{root_path}",
            findings=[
                Finding(
                    title="根目录路径无效",
                    severity="high",
                    detail="无法解析你提供的项目根目录路径。",
                    suggestion="请通过 --root 传入一个真实存在的目录。",
                )
            ],
            recommendations=["检查路径后重新执行命令。"],
            confidence="high",
        )
    if not question.strip():
        return AnalysisReport(
            summary="ask 失败：问题为空。",
            findings=[
                Finding(
                    title="问题为空",
                    severity="medium",
                    detail="ask 命令要求 --question 必须是非空字符串。",
                    suggestion="请提供一个关于代码库的自然语言问题。",
                )
            ],
            recommendations=["示例：`ask --question \"这个项目是做什么的？\"`"],
            confidence="high",
        )

    try:
        chat_model = create_langchain_chat_model(provider=provider)
    except LLMConfigError as exc:
        return AnalysisReport(
            summary=f"ask 失败：{exc}",
            findings=[
                Finding(
                    title="大模型配置无效",
                    severity="high",
                    detail=str(exc),
                    suggestion="请配置 CODEINSIGHT_LLM_PROVIDER 以及对应 Provider 的 API Key。",
                )
            ],
            recommendations=["可先使用 `CODEINSIGHT_LLM_PROVIDER=ollama` 连接本地 Ollama。"],
            confidence="high",
        )

    # 加载项目长期记忆。
    memory = ProjectMemory(root=root_path)
    memory_context = memory.build_context()

    tools, get_evidence = create_tools(str(root_path), memory=memory)
    ask_graph = build_ask_graph(chat_model, tools, memory_context)

    try:
        result = ask_graph.invoke({"messages": [HumanMessage(content=question.strip())]})
    except Exception as exc:
        return AnalysisReport(
            summary=f"ask 调用大模型失败：{exc}",
            findings=[
                Finding(
                    title="大模型调用失败",
                    severity="high",
                    detail=str(exc),
                    suggestion="请检查网络、模型名称、base_url 和 API Key 是否正确。",
                )
            ],
            recommendations=["确认 Provider 配置后重试。"],
            confidence="medium",
        )

    answer = result.get("final_answer", "")
    steps_planned = len(result.get("plan_steps", []))
    steps_completed = result.get("current_step", 0)
    iterations = result.get("iteration", 0)
    if not answer:
        answer = "Agent 未生成最终回答，请检查模型服务或尝试换一种问法。"

    # 收集 Agent 工具调用产生的证据链。
    evidence = get_evidence()
    tool_count = len({ev.reason.split("]")[0].lstrip("[") for ev in evidence if ev.reason.startswith("[Agent")})

    # 将本次问答存入项目长期记忆。
    try:
        memory.add_history(question.strip(), answer)
    except OSError:
        pass

    return AnalysisReport(
        summary=answer,
        findings=[
            Finding(
                title="ask 已完成多步自主分析",
                severity="info",
                detail=(
                    f"Planner 拆解为 {steps_planned} 个子任务，"
                    f"Executor 执行了 {steps_completed} 步，"
                    f"Reviewer 审查了 {iterations} 次，"
                    f"调用 {tool_count} 种工具、收集 {len(evidence)} 条证据。"
                ),
                suggestion="如回答不够具体，可在问题中明确函数名、文件路径或粘贴 traceback。",
            )
        ],
        evidence=evidence[:15],
        recommendations=["继续使用 ask 追问具体文件、函数或错误现象。"],
        confidence="medium",
    )


# —— review 命令 ——

def run_review(
    root: str,
    file_path: str,
    provider: str | None = None,
    max_lines: int = 400,
) -> AnalysisReport:
    """对指定项目文件执行只读代码审查。"""
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"review 失败：项目根目录不存在：{root_path}",
            findings=[
                Finding(
                    title="根目录路径无效",
                    severity="high",
                    detail="无法解析你提供的项目根目录路径。",
                    suggestion="请通过 --root 传入一个真实存在的目录。",
                )
            ],
            recommendations=["检查路径后重新执行命令。"],
            confidence="high",
        )
    if not file_path.strip():
        return AnalysisReport(
            summary="review 失败：文件路径为空。",
            findings=[
                Finding(
                    title="文件路径为空",
                    severity="medium",
                    detail="review 命令要求 --path 必须是非空字符串。",
                    suggestion="请传入相对于 --root 的文件路径。",
                )
            ],
            recommendations=["示例：`review --path src/codeinsight/agent.py`"],
            confidence="high",
        )

    read_report = run_read(str(root_path), file_path, start_line=1, end_line=None, max_lines=max_lines)
    if not read_report.evidence:
        return AnalysisReport(
            summary=f"review 失败：无法读取待审查文件 {file_path!r}。",
            findings=[
                Finding(
                    title="待审查文件读取失败",
                    severity="high",
                    detail=read_report.summary,
                    suggestion="请确认文件位于项目根目录内、不是敏感文件，且为 UTF-8 文本。",
                )
            ],
            evidence=read_report.evidence,
            recommendations=["可先使用 read 命令验证文件是否可读取。"],
            confidence="high",
        )

    try:
        chat_model = create_langchain_chat_model(provider=provider)
    except LLMConfigError as exc:
        return AnalysisReport(
            summary=f"review 失败：{exc}",
            findings=[
                Finding(
                    title="大模型配置无效",
                    severity="high",
                    detail=str(exc),
                    suggestion="请配置 CODEINSIGHT_LLM_PROVIDER 以及对应 Provider 的 API Key。",
                )
            ],
            recommendations=["可先使用 `CODEINSIGHT_LLM_PROVIDER=ollama` 连接本地 Ollama。"],
            confidence="high",
        )

    review_prompt = (
        f"项目根目录：{root_path}\n"
        f"待审查文件：{file_path}\n\n"
        "以下是只读读取工具返回的文件内容：\n\n"
        f"{_report_to_text(read_report)}"
    )
    try:
        response = chat_model.invoke([
            SystemMessage(content=REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=review_prompt),
        ])
        answer = str(response.content) if response.content else "大模型没有返回有效审查内容。"
    except Exception as exc:
        return AnalysisReport(
            summary=f"review 调用大模型失败：{exc}",
            findings=[
                Finding(
                    title="大模型调用失败",
                    severity="high",
                    detail=str(exc),
                    suggestion="请检查网络、模型名称、base_url 和 API Key 是否正确。",
                )
            ],
            recommendations=["确认 Provider 配置后重试。"],
            confidence="medium",
        )

    return AnalysisReport(
        summary=answer,
        findings=[
            Finding(
                title="review 已完成只读代码审查",
                severity="info",
                detail=f"大模型已基于文件 {file_path!r} 的只读内容生成审查建议。",
                suggestion="如文件较大，可分段 review，或结合 ask 追问具体风险点。",
            )
        ],
        evidence=read_report.evidence[:3],
        recommendations=["优先处理审查结果中的正确性、安全性和异常处理问题。"],
        confidence="medium",
    )
