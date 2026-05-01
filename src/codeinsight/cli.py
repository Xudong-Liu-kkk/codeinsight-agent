"""CodeInsight Agent 的命令行入口模块。

V1 先固定命令协议与输出格式，再逐步增强内部分析能力，
这样可以在功能迭代时保持用户使用方式稳定。
"""

import argparse
import json
from typing import Any

from codeinsight.engine import run_overview, run_search
from codeinsight.schemas import AnalysisReport


def _render_report_text(report: AnalysisReport) -> str:
    """将结构化报告渲染为终端友好的文本格式。"""

    # lines 用于按段落累积输出文本，最后统一 join，便于维护格式。
    lines: list[str] = [f"摘要：{report.summary}", ""]
    if report.findings:
        lines.append("发现：")
        # item 表示单条发现，逐条拼接到可读输出中。
        for item in report.findings:
            # 将严重程度内联展示，帮助用户快速识别优先级。
            lines.append(f"- [{item.severity}] {item.title}: {item.detail}")
            lines.append(f"  建议：{item.suggestion}")
    if report.recommendations:
        lines.append("")
        lines.append("建议清单：")
        # rec 表示单条建议，按列表形式输出。
        for rec in report.recommendations:
            lines.append(f"- {rec}")
    lines.append("")
    lines.append(f"置信度：{report.confidence}")
    return "\n".join(lines)


def _print_report(report: AnalysisReport, as_json: bool) -> None:
    """根据输出模式打印报告（JSON 或文本）。"""

    # as_json 为 True 时输出结构化 JSON，便于机器读取和二次处理。
    if as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return
    # 默认输出面向人的文本格式，便于终端阅读。
    print(_render_report_text(report))


def _build_parser() -> argparse.ArgumentParser:
    """定义 V1 CLI 的参数结构与子命令。"""

    # parser 是顶层参数解析器，统一管理所有子命令。
    parser = argparse.ArgumentParser(prog="codeinsight", description="只读代码库分析命令行工具。")
    # subparsers 用于挂载 overview/search 等子命令。
    subparsers = parser.add_subparsers(dest="command", required=True)

    # overview_parser 负责“项目概览”命令参数。
    overview_parser = subparsers.add_parser("overview", help="生成基础项目概览。")
    overview_parser.add_argument("--root", required=True, help="需要分析的项目根目录。")
    overview_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # search_parser 负责“代码搜索”命令参数。
    search_parser = subparsers.add_parser("search", help="按关键词搜索代码库（骨架版）。")
    search_parser.add_argument("--root", required=True, help="执行搜索的项目根目录。")
    search_parser.add_argument("--query", required=True, help="要搜索的关键词或符号。")
    search_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口：解析参数并分发到对应引擎函数。"""

    # 先构建参数解析器，确保命令协议集中定义。
    parser = _build_parser()
    # args 保存解析后的命令行参数对象。
    args = parser.parse_args(argv)
    # args_dict 将参数对象转为字典，便于按键访问。
    args_dict: dict[str, Any] = vars(args)

    # 根据命令类型分发到概览处理逻辑。
    if args.command == "overview":
        # report 是概览命令返回的统一结构化报告。
        report = run_overview(args_dict["root"])
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到搜索处理逻辑。
    if args.command == "search":
        # report 是搜索命令返回的统一结构化报告。
        report = run_search(args_dict["root"], args_dict["query"])
        _print_report(report, args_dict["json"])
        return 0

    # 理论上不会到达此分支；保留兜底可提高健壮性。
    parser.error(f"不支持的命令：{args.command}")
    return 2

