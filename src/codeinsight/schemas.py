"""V1 只读流程使用的共享数据结构定义。

本模块的核心目标是统一输出协议，确保命令行层、引擎层和后续工具层
可以围绕同一份报告结构协作，避免接口频繁变化。
"""

from dataclasses import asdict, dataclass, field
from enum import Enum


class IntentType(str, Enum):
    """当前 CLI 支持的高层意图类型。"""

    PROJECT_OVERVIEW = "project_overview"
    SYMBOL_SEARCH = "symbol_search"
    ERROR_DIAGNOSIS = "error_diagnosis"
    GENERAL_QA = "general_qa"


@dataclass(slots=True)
class CodeEvidence:
    """表示一条可追溯的代码证据。"""

    # 证据来源文件路径（通常是相对项目根目录或可读绝对路径）。
    file_path: str
    # 证据片段起始行号（闭区间）。
    start_line: int
    # 证据片段结束行号（闭区间）。
    end_line: int
    # 证据片段文本内容（可用于回答展示）。
    snippet: str
    # 选择该证据的原因说明，帮助用户理解关联性。
    reason: str


@dataclass(slots=True)
class Finding:
    """表示一条面向用户的问题发现或结论。"""

    # 发现标题，强调问题或结论主题。
    title: str
    # 严重程度，例如 high / medium / info。
    severity: str
    # 对发现内容的详细描述。
    detail: str
    # 可执行的改进建议。
    suggestion: str


@dataclass(slots=True)
class AnalysisReport:
    """引擎函数与 CLI 命令统一返回的分析报告对象。"""

    # 报告摘要，用于快速传达本次分析的核心结论。
    summary: str
    # 发现列表，按需要承载问题、风险和提示信息。
    findings: list[Finding] = field(default_factory=list)
    # 证据列表，保证回答具备可解释性与可追溯性。
    evidence: list[CodeEvidence] = field(default_factory=list)
    # 建议列表，给出下一步行动方向。
    recommendations: list[str] = field(default_factory=list)
    # 置信度标签，表示当前结论的可靠程度。
    confidence: str = "medium"

    def to_dict(self) -> dict:
        """将嵌套 dataclass 转换为普通字典，便于 JSON 输出。"""

        # 使用标准库 asdict 递归展开嵌套结构，输出更稳定。
        return asdict(self)

