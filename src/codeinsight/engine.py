"""V1 骨架阶段的核心命令处理函数。

当前实现优先保证“行为稳定 + 输出结构稳定”。
后续批次会逐步替换为真实工具调用，但对外报告协议保持不变。
"""

from pathlib import Path

from codeinsight.schemas import AnalysisReport, Finding


def run_overview(root: str) -> AnalysisReport:
    """生成项目概览报告（骨架版本）。

    参数:
        root: 需要分析的项目根目录路径。

    返回:
        AnalysisReport: 统一结构化报告对象。
    """

    # 将用户输入路径规范化为绝对路径，减少路径歧义。
    root_path = Path(root).resolve()
    if not root_path.exists():
        # 使用结构化错误返回而非抛异常，保证 CLI 体验稳定可预期。
        return AnalysisReport(
            summary=f"项目根目录不存在：{root_path}",
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

    # 第一批仅采样顶层目录项，后续再替换为更完整的目录树工具。
    top_entries = sorted(p.name for p in root_path.iterdir())[:10]
    return AnalysisReport(
        summary="已生成基础项目概览（第一批骨架版）。",
        findings=[
            Finding(
                title="已采样顶层目录项",
                severity="info",
                detail=f"在项目根目录检测到 {len(top_entries)} 个条目（展示前 10 个）。",
                suggestion="后续可接入目录树工具做更深入分析。",
            )
        ],
        recommendations=["可继续执行 `search` 进行符号级探索。"],
        confidence="medium",
    )


def run_search(root: str, query: str) -> AnalysisReport:
    """执行搜索命令（骨架版本）。

    参数:
        root: 搜索根目录路径。
        query: 用户输入的关键词或符号。

    返回:
        AnalysisReport: 统一结构化报告对象。
    """

    # 先保留根目录解析动作，为后续接入真实搜索工具做准备。
    _ = Path(root).resolve()
    if not query.strip():
        # 对空查询做显式兜底，避免进入无意义的搜索流程。
        return AnalysisReport(
            summary="搜索关键词为空。",
            findings=[
                Finding(
                    title="查询内容为空",
                    severity="medium",
                    detail="search 命令要求 --query 必须是非空字符串。",
                    suggestion="请提供关键词、符号名或错误文本。",
                )
            ],
            recommendations=["示例：`--query \"create_agent\"`"],
            confidence="high",
        )

    # 当前为占位返回，下一批会接入 ripgrep 并附带真实证据片段。
    return AnalysisReport(
        summary="search 命令骨架已打通，待接入真实 rg 搜索能力。",
        findings=[
            Finding(
                title="搜索工具尚未完成实现",
                severity="info",
                detail=f"已接收到查询参数：{query!r}",
                suggestion="下一批将接入 ripgrep 并返回证据片段。",
            )
        ],
        recommendations=["在搜索工具接入前，可先使用 `overview` 查看项目概览。"],
        confidence="medium",
    )

