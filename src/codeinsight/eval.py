"""Agent 评估框架模块。

定义标准测试用例，自动运行 ask 并检查回答是否包含预期内容，
生成评估报告。用于量化 Agent 的分析质量和持续改进。

用法：
  uv run codeinsight eval --root .
"""

import json as _json
import time as _time
from dataclasses import dataclass, field
from pathlib import Path

from codeinsight.agent import run_ask


@dataclass(slots=True)
class EvalCase:
    """一条标准评估用例。

    Attributes:
        question: 要提交给 Agent 的自然语言问题。
        expect_keywords: 回答中应包含的关键词列表。
        expect_files: 回答中应引用的文件路径列表。
        category: 评估分类，如 'tools'、'architecture'。
        weight: 权重（默认 1）。
    """

    question: str
    expect_keywords: list[str] = field(default_factory=list)
    expect_files: list[str] = field(default_factory=list)
    category: str = "general"
    weight: float = 1.0


@dataclass(slots=True)
class EvalResult:
    """单条用例的评估结果。"""

    question: str
    category: str
    answer_summary: str
    keywords_hit: list[str]
    keywords_miss: list[str]
    files_hit: list[str]
    files_miss: list[str]
    score: float
    weight: float
    elapsed_ms: int


@dataclass(slots=True)
class EvalReport:
    """整体评估报告。"""

    results: list[EvalResult]
    total_score: float
    max_score: float
    pass_rate: float
    summary: str
    category_scores: dict[str, float]
    comparison: str


def _check_answer(answer: str, case: EvalCase, elapsed_ms: int) -> EvalResult:
    """检查一条回答是否覆盖了预期内容。"""
    answer_lower = answer.lower()

    keywords_hit = [kw for kw in case.expect_keywords if kw.lower() in answer_lower]
    keywords_miss = [kw for kw in case.expect_keywords if kw.lower() not in answer_lower]

    files_hit = [f for f in case.expect_files if f.lower() in answer_lower]
    files_miss = [f for f in case.expect_files if f.lower() not in answer_lower]

    total = len(case.expect_keywords) + len(case.expect_files)
    hit = len(keywords_hit) + len(files_hit)
    score = hit / total if total > 0 else 1.0

    return EvalResult(
        question=case.question,
        category=case.category,
        answer_summary=answer[:300],
        keywords_hit=keywords_hit,
        keywords_miss=keywords_miss,
        files_hit=files_hit,
        files_miss=files_miss,
        score=score,
        weight=case.weight,
        elapsed_ms=elapsed_ms,
    )


# —— 标准题库 ——
# 覆盖项目各分类能力的评估用例，每道题都有明确的预期内容。
# 分类：core（核心理解）、tools（工具能力）、architecture（架构）、language（多语言）

DEFAULT_CASES: list[EvalCase] = [
    # —— core：项目核心理解 ——
    EvalCase(
        question="这个项目是做什么的？",
        expect_keywords=["代码", "分析", "Agent", "LangChain", "LangGraph", "只读"],
        expect_files=["README.md"],
        category="core",
        weight=1.0,
    ),
    EvalCase(
        question="这个项目的核心模块有哪些？",
        expect_keywords=["cli", "agent", "engine", "graph", "tools"],
        expect_files=["cli.py", "agent.py", "engine.py"],
        category="core",
        weight=1.0,
    ),
    EvalCase(
        question="这个项目有哪些 CLI 命令？",
        expect_keywords=["ask", "review", "fix", "deps", "diagnose", "overview", "search", "read", "serve", "eval"],
        expect_files=["cli.py"],
        category="core",
        weight=1.5,
    ),

    # —— tools：工具能力覆盖 ——
    EvalCase(
        question="search 命令和 search_symbol 工具有什么区别？",
        expect_keywords=["search", "关键词", "符号", "索引"],
        expect_files=["search_tool.py", "symbol_index"],
        category="tools",
        weight=1.0,
    ),
    EvalCase(
        question="read 工具如何确保读取的是完整函数而非截断片段？",
        expect_keywords=["语义", "分块", "边界", "函数", "类"],
        expect_files=["chunk_tool.py", "read_tool.py"],
        category="tools",
        weight=1.0,
    ),
    EvalCase(
        question="diagnose 命令支持哪些错误类型的解析？",
        expect_keywords=["异常", "traceback", "诊断", "stack", "Python", "Java", "JS"],
        expect_files=["diagnose_tool.py"],
        category="tools",
        weight=1.0,
    ),
    EvalCase(
        question="find_usages 工具是用来做什么的？",
        expect_keywords=["依赖", "导入", "引用", "影响"],
        expect_files=["agent_tools.py", "memory.py"],
        category="tools",
        weight=1.0,
    ),
    EvalCase(
        question="fix 命令的自动修复流程是怎样的？",
        expect_keywords=["修复", "备份", "回滚", "测试", "diff"],
        expect_files=["fix_tool.py"],
        category="tools",
        weight=1.0,
    ),

    # —— architecture：架构理解 ——
    EvalCase(
        question="这个项目的多 Agent 协作流程是怎样的？",
        expect_keywords=["Planner", "Reader", "Reviewer", "Synthesizer", "Agent"],
        expect_files=["graph.py"],
        category="architecture",
        weight=1.5,
    ),
    EvalCase(
        question="项目记忆系统的长期记忆和短期记忆有什么区别？",
        expect_keywords=["长期", "短期", "session", "history", "跨会话"],
        expect_files=["memory.py", "session.py"],
        category="architecture",
        weight=1.0,
    ),
    EvalCase(
        question="REST API 有哪些端点？/ask/stream 端点是如何工作的？",
        expect_keywords=["SSE", "流式", "planner", "executor", "reviewer"],
        expect_files=["api.py"],
        category="architecture",
        weight=1.5,
    ),
    EvalCase(
        question="这个项目支持哪些大模型 Provider？",
        expect_keywords=["openai", "deepseek", "qwen", "ollama"],
        expect_files=["llm.py"],
        category="architecture",
        weight=1.0,
    ),

    # —— language：多语言支持 ——
    EvalCase(
        question="这个项目支持哪些编程语言的代码解析和分析？",
        expect_keywords=["Python", "Java", "JavaScript", "TypeScript", "Go", "tree-sitter"],
        expect_files=["language_parser.py"],
        category="language",
        weight=1.0,
    ),
    EvalCase(
        question="deps 命令支持哪些依赖配置格式？",
        expect_keywords=["pyproject", "package.json", "pom.xml", "go.mod", "依赖"],
        expect_files=["deps_tool.py"],
        category="language",
        weight=1.0,
    ),
    EvalCase(
        question="Python 和 Java 的错误堆栈解析有什么不同？",
        expect_keywords=["traceback", "stack trace", "Python", "Java", "堆栈"],
        expect_files=["diagnose_tool.py"],
        category="language",
        weight=1.0,
    ),
]


# —— 历史对比 ——

def _load_previous_report(root: Path) -> dict | None:
    """加载上一次评估结果，用于对比。"""
    eval_dir = root / ".codeinsight" / "eval"
    report_path = eval_dir / "last_report.json"
    if not report_path.exists():
        return None
    try:
        return _json.loads(report_path.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        return None


def _save_report(root: Path, report: EvalReport, results_json: list[dict]) -> None:
    """保存当前评估结果，供下次对比。"""
    eval_dir = root / ".codeinsight" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    report_path = eval_dir / "last_report.json"
    report_path.write_text(_json.dumps({
        "total_score": report.total_score,
        "pass_rate": report.pass_rate,
        "category_scores": report.category_scores,
        "results": results_json,
        "timestamp": int(_time.time() * 1000),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _compare_with_previous(
    current: EvalReport, previous: dict | None
) -> str:
    """对比当前和上一次评估结果。"""
    if previous is None:
        return "（首次评估，无历史数据可对比）"

    prev_score = previous.get("total_score", 0)
    prev_pass = previous.get("pass_rate", 0)
    score_delta = current.total_score - prev_score
    pass_delta = current.pass_rate - prev_pass

    lines = [
        f"  上次评估加权均分：{prev_score:.0%} → 本次：{current.total_score:.0%}"
        f"（{'↑' if score_delta >= 0 else '↓'}{abs(score_delta):.0%}）",
        f"  上次通过率：{prev_pass:.0%} → 本次：{current.pass_rate:.0%}"
        f"（{'↑' if pass_delta >= 0 else '↓'}{abs(pass_delta):.0%}）",
    ]

    # 按分类对比。
    prev_cats = previous.get("category_scores", {})
    for cat, score in current.category_scores.items():
        prev_cat_score = prev_cats.get(cat)
        if prev_cat_score is not None:
            delta = score - prev_cat_score
            lines.append(
                f"  分类 [{cat}]：{prev_cat_score:.0%} → {score:.0%}"
                f"（{'↑' if delta >= 0 else '↓'}{abs(delta):.0%}）"
            )

    return "\n".join(lines)


# —— 主入口 ——


def run_eval(
    root: str,
    provider: str | None = None,
    cases: list[EvalCase] | None = None,
) -> EvalReport:
    """运行 Agent 评估。

    依次执行每条测试用例，调用 run_ask 获取回答并打分。
    按分类汇总得分，并与上次评估结果对比。

    Args:
        root: 项目根目录。
        provider: 可选 LLM Provider。
        cases: 自定义测试用例列表，默认使用 DEFAULT_CASES。

    Returns:
        EvalReport 包含各题得分、分类统计和历史对比。
    """
    import sys

    if cases is None:
        cases = DEFAULT_CASES

    root_path = Path(root).resolve()

    results: list[EvalResult] = []
    # 按分类累计加权分数。
    cat_weighted: dict[str, float] = {}  # {category: weighted_score_sum}
    cat_weight: dict[str, float] = {}     # {category: weight_sum}
    total_weighted_score = 0.0
    total_weight = 0.0

    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] [{case.category}] {case.question}", file=sys.stderr)
        t0 = _time.time()
        report = run_ask(root, case.question, provider=provider)
        elapsed = int((_time.time() - t0) * 1000)

        result = _check_answer(report.summary, case, elapsed)
        results.append(result)

        total_weighted_score += result.score * result.weight
        total_weight += result.weight
        cat_weighted[case.category] = cat_weighted.get(case.category, 0) + result.score * result.weight
        cat_weight[case.category] = cat_weight.get(case.category, 0) + result.weight

        # 打印单条结果。
        status = "✓" if result.score >= 0.6 else "✗"
        kw_info = f"{len(result.keywords_hit)}/{len(case.expect_keywords)} 关键词"
        file_info = f"{len(result.files_hit)}/{len(case.expect_files)} 文件"
        print(
            f"  {status} {result.score:.0%} {kw_info} + {file_info}"
            f"（{elapsed}ms）",
            file=sys.stderr,
        )
        if result.keywords_miss:
            print(f"    未命中关键词：{', '.join(result.keywords_miss[:5])}", file=sys.stderr)

    # 计算各分类得分。
    category_scores = {
        cat: cat_weighted[cat] / cat_weight[cat] if cat_weight[cat] > 0 else 0
        for cat in sorted(cat_weighted)
    }

    pass_rate = sum(1 for r in results if r.score >= 0.6) / len(results) if results else 0
    avg_score = total_weighted_score / total_weight if total_weight > 0 else 0

    # 历史对比。
    previous = _load_previous_report(root_path)
    comparison = _compare_with_previous(
        EvalReport(
            results=results,
            total_score=avg_score,
            max_score=1.0,
            pass_rate=pass_rate,
            summary="",
            category_scores=category_scores,
            comparison="",
        ),
        previous,
    )

    # 构建总结。
    cat_lines = "\n".join(f"  [{cat}]：{score:.0%}" for cat, score in category_scores.items())
    summary = (
        f"评估完成：{len(results)} 道题，通过率 {pass_rate:.0%}，"
        f"加权均分 {avg_score:.0%}\n\n"
        f"分类得分：\n{cat_lines}\n\n"
        f"历史对比：\n{comparison}"
    )

    # 保存本次结果。
    results_json = [
        {
            "question": r.question,
            "category": r.category,
            "score": r.score,
            "elapsed_ms": r.elapsed_ms,
            "keywords_hit": r.keywords_hit,
            "files_hit": r.files_hit,
        }
        for r in results
    ]
    _save_report(root_path, EvalReport(
        results=results,
        total_score=avg_score,
        max_score=1.0,
        pass_rate=pass_rate,
        summary=summary,
        category_scores=category_scores,
        comparison=comparison,
    ), results_json)

    return EvalReport(
        results=results,
        total_score=avg_score,
        max_score=1.0,
        pass_rate=pass_rate,
        summary=summary,
        category_scores=category_scores,
        comparison=comparison,
    )
