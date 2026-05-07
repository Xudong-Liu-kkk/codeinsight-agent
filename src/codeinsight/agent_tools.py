"""Agent 可调用工具定义（LangChain 封装 + 证据收集）。

本模块将引擎层的只读能力包装为 LangChain 工具，
并在每次工具调用时自动收集可追溯的代码证据，
供 Agent 在回答中附上证据链。
"""

from collections.abc import Callable

from langchain_core.tools import tool

from codeinsight.engine import run_deps, run_diagnose, run_find_usages, run_overview, run_read, run_search
from codeinsight.memory import ProjectMemory
from codeinsight.schemas import AnalysisReport, CodeEvidence


def _report_to_text(report: AnalysisReport) -> str:
    """将 AnalysisReport 压缩为供 LLM 消费的简洁文本。"""
    lines = [f"摘要：{report.summary}"]
    if report.findings:
        lines.append("发现：")
        for f in report.findings[:5]:
            lines.append(f"- [{f.severity}] {f.title}：{f.detail}")
    if report.evidence:
        lines.append("证据：")
        for ev in report.evidence[:5]:
            snippet = ev.snippet.strip()
            if len(snippet) > 800:
                snippet = snippet[:800] + "\n...（已截断）"
            lines.append(
                f"- {ev.file_path}:{ev.start_line}-{ev.end_line}\n"
                f"```text\n{snippet}\n```"
            )
    if report.recommendations:
        lines.append("建议：")
        for rec in report.recommendations[:3]:
            lines.append(f"- {rec}")
    return "\n".join(lines)


def _save_imports_to_memory(memory: ProjectMemory, file_path: str, source: str) -> None:
    """从 Python 源码中解析 import 语句，存入项目记忆。

    支持 `import xxx` 和 `from xxx import yyy` 两种语法，
    使用 ast 解析，失败时静默跳过（不影响主流程）。
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.append(node.module)
    if imported:
        try:
            memory.save_imports({file_path: imported})
        except OSError:
            pass


def create_tools(root: str, memory: ProjectMemory | None = None) -> tuple[list, Callable[[], list[CodeEvidence]]]:
    """创建绑定到指定项目根目录的工具列表和证据收集器。

    返回 (tools, get_evidence)，其中 get_evidence 是调用后返回
    本次会话中所有工具调用产生的 CodeEvidence 列表。

    如果传入 memory，overview 工具会在扫描后自动将文件索引
    持久化到 .codeinsight/memory/ 目录。
    """
    evidence_registry: list[CodeEvidence] = []
    _seen_evidence: set[tuple[str, int, int]] = set()

    def _add_evidence(tool_label: str, report: AnalysisReport) -> None:
        """将报告证据标记来源后加入注册表，按 (文件, 起行, 止行) 去重。"""
        for ev in report.evidence:
            key = (ev.file_path, ev.start_line, ev.end_line)
            if key in _seen_evidence:
                continue
            _seen_evidence.add(key)
            ev.reason = f"[Agent 调用 {tool_label}] {ev.reason}"
            evidence_registry.append(ev)

    @tool
    def overview(query: str = "") -> str:
        """获取项目结构概览，了解代码库的整体目录组织方式。
        在分析新项目时通常应首先调用此工具，了解项目包含哪些模块和文件。
        """
        report = run_overview(root)
        _add_evidence("overview", report)
        if memory is not None:
            try:
                scanned = memory.scan_and_save()
                if scanned:
                    report.summary += f"（已更新项目记忆，共 {len(scanned)} 个文件）"
            except OSError:
                pass
        return _report_to_text(report)

    @tool
    def search(query: str) -> str:
        """在项目中按关键词搜索代码，返回包含关键词的文件路径、行号和代码行。
        参数 query 为搜索关键词或符号名称，例如函数名、类名、异常名等。
        """
        report = run_search(root, query)
        _add_evidence(f"search('{query}')", report)
        return _report_to_text(report)

    @tool
    def read(
        file_path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> str:
        """读取项目内指定文件的内容片段。
        file_path 为相对于项目根目录的文件路径。
        start_line 为起始行号（从 1 开始），end_line 为结束行号（可选，默认到文件末尾）。
        每次最多返回 200 行。
        """
        report = run_read(root, file_path, start_line=start_line, end_line=end_line, max_lines=200)
        _add_evidence(f"read('{file_path}')", report)
        # 解析 Python 文件的 import 关系，写入项目长期记忆。
        if memory is not None and file_path.endswith(".py") and report.evidence:
            _save_imports_to_memory(memory, file_path, report.evidence[0].snippet)
        return _report_to_text(report)

    @tool
    def diagnose(error_text: str) -> str:
        """解析 Python traceback 或错误文本，定位项目内出错位置并返回诊断报告。
        error_text 应为包含 traceback 或异常信息的完整文本。
        """
        report = run_diagnose(root, text=error_text)
        _add_evidence("diagnose", report)
        return _report_to_text(report)

    @tool
    def deps() -> str:
        """分析项目的依赖配置，查看运行时依赖、开发依赖和锁文件状态。
        当用户询问项目使用了哪些库、依赖关系或包管理时使用。
        """
        report = run_deps(root)
        _add_evidence("deps", report)
        return _report_to_text(report)

    @tool
    def find_usages(module_name: str) -> str:
        """查找项目中哪些文件导入了指定模块（反向依赖查询）。
        module_name 为模块名或文件名，如 'codeinsight.agent'、'engine.py' 或 'agent'。
        用于回答"谁引用了这个模块""改了这里会影响哪些文件"类问题。
        """
        report = run_find_usages(root, module_name)
        _add_evidence(f"find_usages('{module_name}')", report)
        return _report_to_text(report)

    def get_evidence() -> list[CodeEvidence]:
        return list(evidence_registry)

    return [overview, search, read, diagnose, deps, find_usages], get_evidence
