"""CodeInsight Agent 的命令行入口模块。

V1 先固定命令协议与输出格式，再逐步增强内部分析能力，
这样可以在功能迭代时保持用户使用方式稳定。
"""

import argparse
import json
from typing import Any

from codeinsight.agent import run_ask, run_fix, run_pr_review, run_review
from codeinsight.engine import run_deps, run_diagnose, run_overview, run_read, run_search
from codeinsight.llm import load_env_from_dir
from codeinsight.memory import ProjectMemory
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
    if report.evidence:
        lines.append("")
        lines.append("证据链（可追溯每一步分析来源）：")
        for index, evidence_item in enumerate(report.evidence[:15], start=1):
            snippet_preview = evidence_item.snippet.strip()[:120]
            lines.append(
                f"  {index}. {evidence_item.file_path}:{evidence_item.start_line}"
            )
            lines.append(f"     原因：{evidence_item.reason}")
            if snippet_preview:
                lines.append(f"     内容：{snippet_preview}")
            lines.append("")
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
    # subparsers 用于挂载 overview/search/read/diagnose 等子命令。
    subparsers = parser.add_subparsers(dest="command", required=True)

    # overview_parser 负责“项目概览”命令参数。
    overview_parser = subparsers.add_parser("overview", help="生成基础项目概览。")
    overview_parser.add_argument("--root", required=True, help="需要分析的项目根目录。")
    overview_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # search_parser 负责“代码搜索”命令参数。
    search_parser = subparsers.add_parser("search", help="按关键词搜索代码库。")
    search_parser.add_argument("--root", required=True, help="执行搜索的项目根目录。")
    search_parser.add_argument("--query", required=True, help="要搜索的关键词或符号。")
    search_parser.add_argument("--glob", required=False, help="可选文件过滤模式，例如 *.py。")
    search_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # read_parser 负责“文件读取”命令参数。
    read_parser = subparsers.add_parser("read", help="读取项目内安全文件片段。")
    read_parser.add_argument("--root", required=True, help="项目根目录。")
    read_parser.add_argument("--path", required=True, help="相对于项目根目录的文件路径。")
    read_parser.add_argument("--start", type=int, default=1, help="起始行号，默认 1。")
    read_parser.add_argument("--end", type=int, required=False, help="结束行号，默认读取到文件末尾。")
    read_parser.add_argument("--max-lines", type=int, default=300, help="最大返回行数，默认 300。")
    read_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # diagnose_parser 负责“错误诊断”命令参数。
    diagnose_parser = subparsers.add_parser("diagnose", help="根据 Python traceback 生成诊断报告。")
    diagnose_parser.add_argument("--root", required=True, help="需要诊断的项目根目录。")
    diagnose_input = diagnose_parser.add_mutually_exclusive_group(required=True)
    diagnose_input.add_argument("--text", help="直接传入 traceback 或错误文本。")
    diagnose_input.add_argument("--traceback-file", help="从文本文件读取 traceback。")
    diagnose_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # deps_parser 负责"依赖分析"命令参数。
    deps_parser = subparsers.add_parser("deps", help="分析项目依赖配置与风险。")
    deps_parser.add_argument("--root", required=True, help="需要分析的项目根目录。")
    deps_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # ask_parser 负责“自然语言提问”命令参数。
    ask_parser = subparsers.add_parser("ask", help="让大模型基于只读工具分析代码库问题。")
    ask_parser.add_argument("--root", required=True, help="需要分析的项目根目录。")
    ask_parser.add_argument("--question", required=True, help="要提给 Agent 的自然语言问题。")
    ask_parser.add_argument("--provider", required=False, help="可选 Provider，例如 openai、deepseek、qwen、ollama。")
    ask_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # review_parser 负责“代码审查”命令参数。
    review_parser = subparsers.add_parser("review", help="对指定文件执行只读代码审查。")
    review_parser.add_argument("--root", required=True, help="项目根目录。")
    review_parser.add_argument("--path", required=True, help="相对于项目根目录的文件路径。")
    review_parser.add_argument("--provider", required=False, help="可选 Provider，例如 openai、deepseek、qwen、ollama。")
    review_parser.add_argument("--symbol", required=False, help="仅审查文件中指定名称的函数或类。")
    review_parser.add_argument("--max-lines", type=int, default=400, help="最大读取行数，默认 400。")
    review_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # pr_review_parser 负责"Git PR 审查"命令参数。
    pr_review_parser = subparsers.add_parser("pr-review", help="对 Git 变更执行只读 PR 审查。")
    pr_review_parser.add_argument("--root", required=True, help="项目根目录。")
    pr_review_parser.add_argument("--base", required=False, help="对比的基准分支，如 main。与 --head 配合使用。")
    pr_review_parser.add_argument("--head", required=False, help="对比的目标分支，如 feature-x。与 --base 配合使用。")
    pr_review_parser.add_argument("--commit", required=False, help="审查指定的 commit。")
    pr_review_parser.add_argument("--provider", required=False, help="可选 Provider，例如 openai、deepseek、qwen、ollama。")
    pr_review_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    # memory_clear_parser 负责"清空记忆"命令参数。
    mem_clear_parser = subparsers.add_parser("memory-clear", help="清空项目长期记忆。")
    mem_clear_parser.add_argument("--root", required=True, help="项目根目录。")

    # fix_parser 负责"自动修复"命令参数。
    fix_parser = subparsers.add_parser("fix", help="根据 issue 描述自动修复代码。")
    fix_parser.add_argument("--root", required=True, help="项目根目录。")
    fix_parser.add_argument("--issue", required=True, help="要修复的问题描述。")
    fix_parser.add_argument("--provider", required=False, help="可选 Provider。")
    fix_parser.add_argument("--json", action="store_true", help="以 JSON 形式输出报告。")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口：解析参数并分发到对应引擎函数。"""

    # 先加载当前目录的 .env（如果存在）。
    load_env_from_dir(".")

    # 先构建参数解析器，确保命令协议集中定义。
    parser = _build_parser()
    # args 保存解析后的命令行参数对象。
    args = parser.parse_args(argv)
    # args_dict 将参数对象转为字典，便于按键访问。
    args_dict: dict[str, Any] = vars(args)

    # 再加载 --root 目录的 .env（如果指定且不同于当前目录）。
    if args_dict.get("root") and args_dict["root"] != ".":
        load_env_from_dir(args_dict["root"])

    # 根据命令类型分发到概览处理逻辑。
    if args.command == "overview":
        # report 是概览命令返回的统一结构化报告。
        report = run_overview(args_dict["root"])
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到搜索处理逻辑。
    if args.command == "search":
        # report 是搜索命令返回的统一结构化报告。
        report = run_search(args_dict["root"], args_dict["query"], args_dict.get("glob"))
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到文件读取逻辑。
    if args.command == "read":
        # report 是读取命令返回的统一结构化报告。
        report = run_read(
            args_dict["root"],
            args_dict["path"],
            start_line=args_dict["start"],
            end_line=args_dict.get("end"),
            max_lines=args_dict["max_lines"],
        )
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到错误诊断逻辑。
    if args.command == "diagnose":
        # report 是诊断命令返回的统一结构化报告。
        report = run_diagnose(args_dict["root"], text=args_dict.get("text"), traceback_file=args_dict.get("traceback_file"))
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到依赖分析逻辑。
    if args.command == "deps":
        # report 是依赖分析命令返回的统一结构化报告。
        report = run_deps(args_dict["root"])
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到自然语言 ask 逻辑。
    if args.command == "ask":
        # report 是自然语言 Agent 返回的统一结构化报告。
        report = run_ask(args_dict["root"], args_dict["question"], provider=args_dict.get("provider"))
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到 PR 审查逻辑。
    if args.command == "pr-review":
        report = run_pr_review(
            args_dict["root"],
            base=args_dict.get("base"),
            head=args_dict.get("head"),
            commit=args_dict.get("commit"),
            provider=args_dict.get("provider"),
        )
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到自动修复逻辑。
    if args.command == "fix":
        report = run_fix(args_dict["root"], args_dict["issue"], provider=args_dict.get("provider"))
        _print_report(report, args_dict["json"])
        return 0

    # 根据命令类型分发到记忆清空逻辑。
    if args.command == "memory-clear":
        from pathlib import Path

        root_path = Path(args_dict["root"]).resolve()
        if root_path.exists() and root_path.is_dir():
            memory = ProjectMemory(root=root_path)
            memory.clear()
            print(f"已清空项目记忆：{memory.memory_dir}")
        else:
            print(f"项目根目录不存在：{root_path}")
        return 0

    # review 是剩余的合法命令；argparse 已保证不会出现其他命令。
    # report 是代码审查命令返回的统一结构化报告。
    report = run_review(
        args_dict["root"],
        args_dict["path"],
        symbol=args_dict.get("symbol"),
        provider=args_dict.get("provider"),
        max_lines=args_dict["max_lines"],
    )
    _print_report(report, args_dict["json"])
    return 0
