"""Agent 评估框架模块。

定义标准测试用例，自动运行 ask 并检查回答是否包含预期内容，
生成评估报告。用于量化 Agent 的分析质量和持续改进。

用法：
  uv run codeinsight eval --root .
"""

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
        weight: 权重，复杂问题可以给更高权重（默认 1）。
    """

    question: str
    expect_keywords: list[str] = field(default_factory=list)
    expect_files: list[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass(slots=True)
class EvalResult:
    """单条用例的评估结果。"""

    question: str
    answer_summary: str
    keywords_hit: list[str]
    keywords_miss: list[str]
    files_hit: list[str]
    files_miss: list[str]
    score: float
    weight: float


@dataclass(slots=True)
class EvalReport:
    """整体评估报告。"""

    results: list[EvalResult]
    total_score: float
    max_score: float
    pass_rate: float
    summary: str


def _check_answer(answer: str, case: EvalCase) -> EvalResult:
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
        answer_summary=answer[:300],
        keywords_hit=keywords_hit,
        keywords_miss=keywords_miss,
        files_hit=files_hit,
        files_miss=files_miss,
        score=score,
        weight=case.weight,
    )


# —— 标准题库 ——
# 覆盖项目核心能力的评估用例，每道题都有明确的预期内容。

DEFAULT_CASES: list[EvalCase] = [
    EvalCase(
        question="这个项目是做什么的？",
        expect_keywords=["代码", "分析", "Agent", "LangChain", "LangGraph", "只读"],
        expect_files=["README.md"],
        weight=1.0,
    ),
    EvalCase(
        question="这个项目的核心模块有哪些？",
        expect_keywords=["cli", "agent", "engine", "graph", "tools"],
        expect_files=["cli.py", "agent.py", "engine.py"],
        weight=1.0,
    ),
    EvalCase(
        question="这个项目支持哪些大模型 Provider？",
        expect_keywords=["openai", "deepseek", "qwen", "ollama"],
        expect_files=["llm.py"],
        weight=1.0,
    ),
    EvalCase(
        question="这个项目的依赖分析功能是怎么实现的？",
        expect_keywords=["deps", "pyproject", "toml", "依赖"],
        expect_files=["deps_tool.py", "engine.py"],
        weight=1.0,
    ),
    EvalCase(
        question="这个项目有哪些 CLI 命令？",
        expect_keywords=["ask", "review", "fix", "deps", "diagnose", "pr-review"],
        expect_files=["cli.py"],
        weight=1.5,
    ),
]


def run_eval(root: str, provider: str | None = None, cases: list[EvalCase] | None = None) -> EvalReport:
    """运行 Agent 评估。

    依次执行每条测试用例，调用 run_ask 获取回答并打分。

    Args:
        root: 项目根目录。
        provider: 可选 LLM Provider。
        cases: 自定义测试用例列表，默认使用 DEFAULT_CASES。

    Returns:
        EvalReport 包含各题得分和总体统计。
    """
    if cases is None:
        cases = DEFAULT_CASES

    results: list[EvalResult] = []
    total_weighted_score = 0.0
    total_weight = 0.0

    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] 评估：{case.question}", file=__import__("sys").stderr)
        report = run_ask(root, case.question, provider=provider)
        result = _check_answer(report.summary, case)
        results.append(result)

        total_weighted_score += result.score * result.weight
        total_weight += result.weight

        # 打印单条结果。
        status = "✓" if result.score >= 0.6 else "✗"
        print(f"  {status} 得分 {result.score:.0%} 命中 {len(result.keywords_hit)}/{len(case.expect_keywords)} 关键词"
              f" + {len(result.files_hit)}/{len(case.expect_files)} 文件",
              file=__import__("sys").stderr)
        if result.keywords_miss:
            print(f"    未命中关键词：{', '.join(result.keywords_miss)}", file=__import__("sys").stderr)
        if result.files_miss:
            print(f"    未引用文件：{', '.join(result.files_miss)}", file=__import__("sys").stderr)

    pass_rate = sum(1 for r in results if r.score >= 0.6) / len(results) if results else 0
    avg_score = total_weighted_score / total_weight if total_weight > 0 else 0

    return EvalReport(
        results=results,
        total_score=avg_score,
        max_score=1.0,
        pass_rate=pass_rate,
        summary=(
            f"评估完成：{len(results)} 道题，通过率 {pass_rate:.0%}，"
            f"加权平均分 {avg_score:.0%}"
        ),
    )
