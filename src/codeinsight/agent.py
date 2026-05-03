"""自然语言 ask Agent 编排层。

ask 命令是 CodeInsight Agent 的核心入口：
它把用户问题、项目只读工具结果和大模型 Provider 连接起来，
让模型基于真实代码库上下文生成回答。
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from codeinsight.engine import run_diagnose, run_overview, run_read, run_search
from codeinsight.llm import LLMConfigError, create_llm_client
from codeinsight.schemas import AnalysisReport, CodeEvidence, Finding


class ChatClient(Protocol):
    """ask Agent 依赖的最小聊天客户端协议。"""

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """发送聊天消息并返回文本回答。"""


@dataclass(slots=True)
class ToolContext:
    """一次 ask 调用收集到的工具上下文。"""

    # overview_report 是项目结构概览报告。
    overview_report: AnalysisReport
    # search_reports 是根据问题关键词触发的搜索报告列表。
    search_reports: list[AnalysisReport]
    # read_reports 是从搜索证据继续读取的源码片段报告列表。
    read_reports: list[AnalysisReport]
    # diagnose_report 是检测到 traceback 时生成的诊断报告。
    diagnose_report: AnalysisReport | None = None


def _report_to_prompt_section(title: str, report: AnalysisReport) -> str:
    """将结构化报告压缩成适合放入 prompt 的文本片段。"""

    # lines 按固定顺序组织报告内容，避免 prompt 上下文过于散乱。
    lines: list[str] = [f"## {title}", f"摘要：{report.summary}"]
    if report.findings:
        lines.append("发现：")
        for finding in report.findings[:5]:
            lines.append(f"- [{finding.severity}] {finding.title}：{finding.detail}")
    if report.evidence:
        lines.append("证据：")
        for evidence in report.evidence[:5]:
            snippet = evidence.snippet.strip()
            if len(snippet) > 1200:
                snippet = snippet[:1200] + "\n...（已截断）"
            lines.append(
                f"- {evidence.file_path}:{evidence.start_line}-{evidence.end_line}\n"
                f"```text\n{snippet}\n```"
            )
    if report.recommendations:
        lines.append("建议：")
        for recommendation in report.recommendations[:5]:
            lines.append(f"- {recommendation}")
    return "\n".join(lines)


def _extract_query_terms(question: str, max_terms: int = 3) -> list[str]:
    """从自然语言问题中提取少量适合搜索的关键词。"""

    # quoted_terms 优先保留用户显式用引号或反引号圈出的符号。
    quoted_terms = re.findall(r"[`'\"]([^`'\"]{2,80})[`'\"]", question)
    # identifier_terms 提取 Python/配置中常见的符号形态。
    identifier_terms = re.findall(r"[A-Za-z_][A-Za-z0-9_\.]{2,}", question)
    # terms 按出现顺序去重，避免重复搜索同一关键词。
    terms: list[str] = []
    for term in [*quoted_terms, *identifier_terms]:
        normalized = term.strip()
        if normalized and normalized not in terms:
            terms.append(normalized)
        if len(terms) >= max_terms:
            break
    return terms


def _looks_like_traceback(question: str) -> bool:
    """粗略判断用户输入是否包含 Python traceback。"""

    return "Traceback (most recent call last)" in question or bool(re.search(r"\b[A-Za-z_][\w.]*Error:", question))


def _collect_tool_context(root: str, question: str) -> ToolContext:
    """根据用户问题自动收集只读工具上下文。"""

    # overview 是默认上下文，让模型先知道项目大致结构。
    overview_report = run_overview(root)
    search_reports: list[AnalysisReport] = []
    read_reports: list[AnalysisReport] = []

    for term in _extract_query_terms(question):
        search_report = run_search(root, term, glob_pattern="*.py")
        search_reports.append(search_report)
        # 对每个搜索词只读取前两条证据，控制上下文体积。
        for evidence in search_report.evidence[:2]:
            try:
                relative_path = str(Path(evidence.file_path).resolve().relative_to(Path(root).resolve()))
            except ValueError:
                relative_path = evidence.file_path
            read_reports.append(
                run_read(
                    root,
                    relative_path,
                    start_line=max(1, evidence.start_line - 8),
                    end_line=evidence.end_line + 8,
                    max_lines=17,
                )
            )

    diagnose_report = run_diagnose(root, text=question) if _looks_like_traceback(question) else None
    return ToolContext(
        overview_report=overview_report,
        search_reports=search_reports,
        read_reports=read_reports,
        diagnose_report=diagnose_report,
    )


def _build_messages(root: str, question: str, context: ToolContext) -> list[dict[str, str]]:
    """构造发送给大模型的消息。"""

    # context_sections 保存所有工具结果，用于作为模型回答依据。
    context_sections = [_report_to_prompt_section("项目概览", context.overview_report)]
    for index, report in enumerate(context.search_reports, start=1):
        context_sections.append(_report_to_prompt_section(f"搜索结果 {index}", report))
    for index, report in enumerate(context.read_reports, start=1):
        context_sections.append(_report_to_prompt_section(f"源码片段 {index}", report))
    if context.diagnose_report is not None:
        context_sections.append(_report_to_prompt_section("错误诊断", context.diagnose_report))

    system_prompt = (
        "你是 CodeInsight Agent，一个只读代码库分析助手。"
        "你只能基于用户问题和工具上下文进行分析，不能声称已经修改代码。"
        "回答必须使用中文，结论要可追溯；如果上下文不足，要明确说明还需要搜索或读取哪些文件。"
        "优先给出：结论、依据、下一步建议。"
    )
    user_prompt = (
        f"项目根目录：{Path(root).resolve()}\n\n"
        f"用户问题：\n{question}\n\n"
        "以下是只读工具自动收集的上下文：\n\n"
        + "\n\n".join(context_sections)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def run_ask(root: str, question: str, provider: str | None = None, client: ChatClient | None = None) -> AnalysisReport:
    """运行自然语言 ask Agent。"""

    # root_path 表示规范化后的项目根目录。
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

    context = _collect_tool_context(str(root_path), question)
    messages = _build_messages(str(root_path), question.strip(), context)
    try:
        # llm_client 是可注入的聊天客户端，测试时可用假客户端替代真实模型。
        llm_client = client or create_llm_client(provider=provider)
        answer = llm_client.chat(messages, temperature=0.2).strip()
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
    except Exception as exc:  # noqa: BLE001 - CLI 边界需要把模型调用异常转为结构化报告。
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

    if not answer:
        answer = "大模型没有返回有效内容。请尝试换一种问法，或检查模型服务是否正常。"

    evidence: list[CodeEvidence] = []
    for report in [context.overview_report, *context.search_reports, *context.read_reports]:
        evidence.extend(report.evidence[:3])
    if context.diagnose_report is not None:
        evidence.extend(context.diagnose_report.evidence[:3])

    return AnalysisReport(
        summary=answer,
        findings=[
            Finding(
                title="ask 已完成大模型分析",
                severity="info",
                detail="大模型已基于 overview/search/read/diagnose 等只读工具上下文生成回答。",
                suggestion="如回答不够具体，可在问题中明确函数名、文件路径或粘贴 traceback。",
            )
        ],
        evidence=evidence[:10],
        recommendations=["继续使用 ask 追问具体文件、函数或错误现象。"],
        confidence="medium",
    )
