"""CodeInsight Agent 编排层。

本模块提供三个 Agent 入口，底层通过 LangChain 框架调用只读工具
并由大模型生成回答：

  run_ask()      — 自然语言问答，通过 LangGraph 多步自主分析图执行
  run_review()   — 单文件只读代码审查
  run_pr_review()— Git 变更 PR 审查，组合 git diff + 文件读取 + LLM

每个入口均返回统一的 AnalysisReport 结构，包含回答摘要、发现列表、
证据链（可追溯结论来源）、建议清单和置信度。
"""

from pathlib import Path
import sys

from langchain_core.messages import HumanMessage, SystemMessage

from codeinsight.agent_tools import _report_to_text, create_tools
from codeinsight.engine import run_read, run_search
from codeinsight.fix_tool import apply_fix, generate_diff
from codeinsight.git_tool import get_branch_diff, get_commit_diff, get_uncommitted_diff
from codeinsight.tools.symbol_tool import find_symbol_source
from codeinsight.graph import build_ask_graph
from codeinsight.llm import LLMConfigError, create_langchain_chat_model, load_env_from_dir
from codeinsight.memory import ProjectMemory
from codeinsight.schemas import AnalysisReport, CodeEvidence, Finding

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
    load_env_from_dir(root)
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

    # 节点级进度走外层 stream，逐 token 输出在 graph.py 的 Executor 内部处理。
    result: dict = {}
    steps_count = 0
    try:
        for chunk in ask_graph.stream(
            {"messages": [HumanMessage(content=question.strip())]},
            stream_mode="updates",
        ):
            for node_name, node_output in chunk.items():
                if node_name == "planner":
                    steps_count = len(node_output.get("plan_steps", []))
                    print(f"\n→ Planner 拆解为 {steps_count} 个子任务：", file=sys.stderr, flush=True)
                    for i, step in enumerate(node_output.get("plan_steps", []), 1):
                        print(f"  [{i}] {step}", file=sys.stderr, flush=True)
                elif node_name == "executor":
                    idx = node_output.get("current_step", 0)
                    if steps_count:
                        print(f"\n── [{idx}/{steps_count}] Executor 开始执行 ──", file=sys.stderr, flush=True)
                elif node_name == "reviewer":
                    is_ok = node_output.get("is_sufficient", "NO")
                    it = node_output.get("iteration", 0)
                    label = "✓ 充分" if is_ok == "YES" else "✗ 不足，将补充执行"
                    print(f"\n→ Reviewer 审查结果：{label}（第 {it} 轮）", file=sys.stderr, flush=True)
                elif node_name == "synthesizer":
                    print(f"\n→ Synthesizer 正在汇总生成回答：\n", file=sys.stderr, flush=True)
                result.update(node_output)
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
    symbol: str | None = None,
    provider: str | None = None,
    max_lines: int = 400,
) -> AnalysisReport:
    """对指定项目文件（或其中的符号）执行只读代码审查。

    Args:
        root: 项目根目录。
        file_path: 相对于 root 的文件路径。
        symbol: 可选的要审查的符号名（函数或类）。
                传入时只审查该符号的源码，而非整个文件。
        provider: 可选的 LLM Provider 名称。
        max_lines: 审查整个文件时的最大读取行数。
    """
    load_env_from_dir(root)
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

    # —— 读取文件内容 ——
    # 如果指定了 symbol，先读整个文件再用 ast 提取目标符号源码。
    # 如果未指定 symbol，直接读取文件片段。
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

    # 符号提取：用 ast 精确定位函数或类的源码片段。
    review_content = _report_to_text(read_report)
    review_target = f"文件 {file_path!r}"
    if symbol:
        safe_path = (root_path / file_path).resolve()
        symbol_source = find_symbol_source(safe_path, symbol)
        if symbol_source:
            review_content = symbol_source
            review_target = f"文件 {file_path!r} 中的符号 {symbol!r}"
        else:
            return AnalysisReport(
                summary=f"review 失败：未在 {file_path!r} 中找到符号 {symbol!r}。",
                findings=[
                    Finding(
                        title="符号未找到",
                        severity="medium",
                        detail=f"在文件 {file_path!r} 中未找到名为 {symbol!r} 的函数或类。",
                        suggestion="请确认符号名拼写正确，区分大小写。",
                    )
                ],
                recommendations=["可先使用 read 命令查看文件内容，确认符号名称。"],
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
        f"待审查目标：{review_target}\n\n"
        "以下是待审查的代码内容：\n\n"
        f"{review_content}"
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
                detail=f"大模型已基于 {review_target} 的只读内容生成审查建议。",
                suggestion="如文件较大，可分段 review，或结合 ask 追问具体风险点。",
            )
        ],
        evidence=read_report.evidence[:3],
        recommendations=["优先处理审查结果中的正确性、安全性和异常处理问题。"],
        confidence="medium",
    )


# —— pr-review 命令 ——
# 对 Git 变更进行只读审查，组合 git diff + read + LLM 三步流程。

PR_REVIEW_SYSTEM_PROMPT = (
    "你是 CodeInsight Agent 的 Git PR 代码审查助手。"
    "你只能审查和解释代码变更，不能声称已经修改代码。"
    "回答必须使用中文，并按以下结构输出：\n\n"
    "## 变更概要\n（本次变更做了什么，涉及哪些文件）\n\n"
    "## 风险评估\n"
    "- 🛑 高风险：可能导致运行时异常、数据丢失、安全问题\n"
    "- ⚠️ 中风险：可能导致边缘情况异常、性能退化\n"
    "- ℹ️ 低风险：样式、注释、命名调整\n\n"
    "## 逐文件 Review\n对每个变更文件给出具体评价和改进建议\n\n"
    "## 总结建议\n（合并前建议补充的操作，如测试、文档、CI 检查）"
)


def run_pr_review(
    root: str,
    base: str | None = None,
    head: str | None = None,
    commit: str | None = None,
    provider: str | None = None,
    max_files: int = 10,
) -> AnalysisReport:
    """对 Git 变更执行只读 PR 审查。

    工作流：
      1. 通过 git diff（或 git show）获取变更内容和文件列表
      2. 对每个变更文件调 run_read 读取当前完整内容
      3. 将 diff + 文件内容组装为审查 prompt，交给大模型
      4. 模型按"变更概要 → 风险评估 → 逐文件 Review → 总结建议"结构输出

    Args:
        root: 项目根目录。
        base: 基准分支名（预留，当前未实现分支对比）。
        head: 目标分支名（预留，当前未实现分支对比）。
        commit: 要审查的 commit-ish，如 "HEAD"、"abc1234"。不传则审查未提交的变更。
        provider: 可选的 Provider 名称，不传则使用环境变量配置。
        max_files: 最多读取并审查的文件数量，超出的文件仅在 diff 中显示。

    Returns:
        统一 AnalysisReport，summary 字段包含完整的审查报告文本。
    """

    # 确保 --root 目录下的 .env 文件（如果存在）已被加载，
    # 这样即使直接调用 run_pr_review 而非通过 CLI 入口也能读取配置。
    load_env_from_dir(root)
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"pr-review 失败：项目根目录不存在：{root_path}",
            findings=[
                Finding(
                    title="根目录路径无效", severity="high",
                    detail="无法解析你提供的项目根目录路径。",
                    suggestion="请通过 --root 传入一个真实存在的目录。",
                )
            ],
            recommendations=["检查路径后重新执行命令。"],
            confidence="high",
        )

    # —— 第一步：获取 Git 变更 ——
    # 三种模式（按优先级）：
    #   1. --commit 指定时，审查该 commit 的变更（git show）。
    #   2. --base + --head 指定时，审查两个分支的差异（三点语法）。
    #   3. 默认审查工作区未提交的变更（git diff + git diff --cached）。
    try:
        if commit:
            diff = get_commit_diff(root_path, commit)
        elif base and head:
            diff = get_branch_diff(root_path, base, head)
        else:
            diff = get_uncommitted_diff(root_path)
    except RuntimeError as exc:
        return AnalysisReport(
            summary=f"pr-review 失败：Git 操作异常：{exc}",
            findings=[
                Finding(
                    title="Git 命令执行失败", severity="high",
                    detail=str(exc),
                    suggestion="请确认当前目录是 Git 仓库，且 git 命令可用。",
                )
            ],
            recommendations=["在项目根目录下执行 pr-review 命令。"],
            confidence="high",
        )

    if not diff.files_changed or not diff.diff_content.strip():
        return AnalysisReport(
            summary="pr-review：未检测到代码变更。",
            findings=[
                Finding(
                    title="无变更文件", severity="info",
                    detail="当前工作区没有未提交的修改。",
                    suggestion="修改代码后再执行 pr-review，或使用 --commit 指定历史提交。",
                )
            ],
            recommendations=[],
            confidence="high",
        )

    # —— 第二步：读取变更文件的当前内容 ——
    # 仅读取前 max_files 个文件，避免 token 溢出。
    # diff_content 也截断到 4000 字符，大型 diff 只审前部。
    evidence_list: list[CodeEvidence] = []
    file_contents: list[str] = []
    for f in diff.files_changed[:max_files]:
        try:
            read_report = run_read(str(root_path), f, start_line=1, end_line=None, max_lines=200)
            if read_report.evidence:
                evidence_list.extend(read_report.evidence)
                file_contents.append(
                    f"=== {f} ===\n{read_report.evidence[0].snippet}"
                )
            else:
                file_contents.append(f"=== {f} ===\n（文件无法读取）")
        except Exception:
            file_contents.append(f"=== {f} ===\n（读取失败）")

    try:
        chat_model = create_langchain_chat_model(provider=provider)
    except LLMConfigError as exc:
        return AnalysisReport(
            summary=f"pr-review 失败：{exc}",
            findings=[
                Finding(
                    title="大模型配置无效", severity="high",
                    detail=str(exc),
                    suggestion="请配置 CODEINSIGHT_LLM_PROVIDER 以及对应 Provider 的 API Key。",
                )
            ],
            recommendations=["可先使用 `CODEINSIGHT_LLM_PROVIDER=ollama` 连接本地 Ollama。"],
            confidence="high",
        )

    # —— 第三步：组装 prompt 并调用大模型 ——
    # 将 diff（变更差异）+ 文件当前内容一起交给模型，让模型既能
    # 看到"改了什么"也能看到"完整的文件长什么样"，避免断章取义。
    review_prompt = (
        f"Git 变更统计：{diff.summary}\n"
        f"变更文件数：{len(diff.files_changed)} 个\n\n"
        "=== Git Diff（变更内容，context=5 行）===\n"
        f"{diff.diff_content[:4000]}\n\n"
        "=== 变更文件当前内容（前 200 行）===\n"
        f"{'\n\n'.join(file_contents)}"
    )

    try:
        response = chat_model.invoke([
            SystemMessage(content=PR_REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=review_prompt),
        ])
        answer = str(response.content) if response.content else "大模型没有返回有效审查内容。"
    except Exception as exc:
        return AnalysisReport(
            summary=f"pr-review 调用大模型失败：{exc}",
            findings=[
                Finding(
                    title="大模型调用失败", severity="high",
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
                title="pr-review 已完成 Git 变更审查",
                severity="info",
                detail=f"审查了 {min(len(diff.files_changed), max_files)}/{len(diff.files_changed)} 个变更文件。{diff.summary}",
                suggestion="优先处理高风险项，补充测试后合并。",
            )
        ],
        evidence=evidence_list[:10],
        recommendations=[
            "审查结果中的高风险项应在合并前修复。",
            "建议对新增或修改的函数补充单元测试。",
            "确认变更不会破坏现有 CI 流程。",
        ],
        confidence="medium",
    )


# —— fix 命令 ——
# 自动修复：搜索 → 读取 → 生成 fix → 用户确认 → 应用。

FIX_SYSTEM_PROMPT = (
    "你是 CodeInsight Agent 的代码修复助手。"
    "基于用户描述的 issue 和相关代码，生成精确的修复方案。"
    "只输出修复方案，格式如下：\n\n"
    "=== FIX ===\n"
    "文件：<文件路径>\n"
    "=== ORIGINAL ===\n"
    "<要替换的原始代码（必须与文件内容精确匹配）>\n"
    "=== REPLACEMENT ===\n"
    "<替换后的新代码>\n"
    "=== END ===\n\n"
    "要求：\n"
    "1. ORIGINAL 代码片段必须与源文件逐字符匹配\n"
    "2. REPLACEMENT 是修复后的完整代码\n"
    "3. 一次只修复一个问题，涉及多处修改时分别列\n"
    "4. 如果不需要改代码（如配置问题），输出 === NONE ==="
)


def run_fix(
    root: str,
    issue: str,
    provider: str | None = None,
    auto_confirm: bool = False,
) -> AnalysisReport:
    """根据 issue 描述自动修复代码。

    工作流：
      1. 用 search 定位 issue 相关的代码文件
      2. 用 read 读取候选文件内容
      3. 让 LLM 生成精确修复方案
      4. 展示 diff，等待用户确认
      5. 用户确认后应用修复，自动创建 .bak 备份

    Args:
        root: 项目根目录。
        issue: 问题描述，如"第 85 行可能返回 None，需要加空值检查"。
        provider: 可选的 LLM Provider。
        auto_confirm: True 时跳过确认步骤（测试用）。
    """
    load_env_from_dir(root)
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"fix 失败：项目根目录不存在：{root_path}",
            findings=[Finding(title="根目录路径无效", severity="high",
                               detail="无法解析你提供的项目根目录路径。",
                               suggestion="请通过 --root 传入一个真实存在的目录。")],
            recommendations=["检查路径后重新执行命令。"], confidence="high",
        )
    if not issue.strip():
        return AnalysisReport(
            summary="fix 失败：issue 为空。",
            findings=[Finding(title="问题描述为空", severity="medium",
                               detail="fix 命令要求 --issue 必须是非空字符串。",
                               suggestion="请描述需要修复的问题。")],
            recommendations=[], confidence="high",
        )

    # —— 第一步：搜索相关代码 ——
    import re as _re
    terms = _re.findall(r"[A-Za-z_][\w\.]{2,}", issue)
    candidate_files: set = set()
    for term in terms[:3]:
        if len(term) < 3:
            continue
        try:
            search_report = run_search(str(root_path), term)
            for ev in search_report.evidence[:5]:
                candidate_files.add(ev.file_path)
        except Exception:
            continue

    if not candidate_files:
        return AnalysisReport(
            summary="fix 失败：未能搜索到与 issue 相关的代码文件。",
            findings=[Finding(title="未找到相关代码", severity="medium",
                               detail="请尝试更具体的问题描述，包含文件名、函数名或行号。",
                               suggestion="示例：`fix --issue \"engine.py 第 85 行返回值可能为 None\"`")],
            recommendations=["先用 search 命令确认关键词能命中目标文件。"],
            confidence="medium",
        )

    # —— 第二步：读取候选文件 ——
    file_snippets: list[str] = []
    for f in sorted(candidate_files)[:5]:
        try:
            read_report = run_read(str(root_path), f, start_line=1, end_line=None, max_lines=300)
            if read_report.evidence:
                file_snippets.append(f"=== {f} ===\n{read_report.evidence[0].snippet}")
        except Exception:
            continue

    # —— 第三步：生成修复方案 ——
    try:
        chat_model = create_langchain_chat_model(provider=provider)
    except LLMConfigError as exc:
        return AnalysisReport(
            summary=f"fix 失败：{exc}",
            findings=[Finding(title="大模型配置无效", severity="high", detail=str(exc),
                               suggestion="请配置 CODEINSIGHT_LLM_PROVIDER 及对应 API Key。")],
            confidence="high",
        )

    fix_prompt = (
        f"用户 Issue：{issue.strip()}\n\n"
        "相关代码文件：\n\n"
        f"{'\n\n'.join(file_snippets)}"
    )
    try:
        response = chat_model.invoke([
            SystemMessage(content=FIX_SYSTEM_PROMPT),
            HumanMessage(content=fix_prompt),
        ])
        reply = str(response.content or "")
    except Exception as exc:
        return AnalysisReport(
            summary=f"fix 调用大模型失败：{exc}",
            findings=[Finding(title="大模型调用失败", severity="high", detail=str(exc),
                               suggestion="检查网络和 API Key。")],
            confidence="medium",
        )

    if "=== NONE ===" in reply:
        return AnalysisReport(
            summary="fix 分析完成：模型判断此问题不需要修改代码。",
            findings=[Finding(title="无需代码修改", severity="info",
                               detail="模型分析后认为该 issue 不涉及代码变更。")],
            confidence="medium",
        )

    # —— 第四步：解析修复方案 ——
    fix_pattern = _re.compile(
        r"=== FIX ===\s*\n文件：(.+?)\n=== ORIGINAL ===\s*\n(.*?)\n=== REPLACEMENT ===\s*\n(.*?)\n=== END ===",
        _re.DOTALL,
    )
    matches = fix_pattern.findall(reply)
    if not matches:
        return AnalysisReport(
            summary=f"fix 分析完成，但未生成可执行的修复方案。模型回复：\n\n{reply[:500]}",
            findings=[Finding(title="修复方案解析失败", severity="medium",
                               detail="模型未按预期格式返回修复方案。")],
            confidence="low",
        )

    # —— 第五步：展示 diff 并确认 ——
    for file_path, original, replacement in matches:
        fp, orig, repl = file_path.strip(), original.strip(), replacement.strip()
        if not orig or not repl:
            continue
        diff_preview = generate_diff(fp, orig, repl)
        print(f"\n--- 修复 {fp} ---", file=sys.stderr)
        print(diff_preview, file=sys.stderr)

    if not auto_confirm:
        try:
            choice = input("\n应用以上修复？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"
        if choice not in ("y", "yes"):
            return AnalysisReport(
                summary="用户取消了修复操作。",
                findings=[Finding(title="修复已取消", severity="info",
                                   detail="用户可以修改 issue 描述后重试。")],
                confidence="medium",
            )

    # —— 第六步：应用修复 ——
    applied, failed = [], []
    for file_path, original, replacement in matches:
        fp = file_path.strip()
        success = apply_fix(fp, original.strip(), replacement.strip())
        (applied if success else failed).append(fp)

    if not applied:
        return AnalysisReport(
            summary="fix 失败：未能应用任何修复。",
            findings=[Finding(title="修复应用失败", severity="high",
                               detail="文件内容可能已变更，导致原始代码片段匹配失败。")],
            confidence="low",
        )

    # —— 第七步：运行测试验证修复 ——
    from codeinsight.fix_tool import rollback as do_rollback, run_tests

    print("\n正在运行测试验证修复...", file=sys.stderr)
    passed, test_output = run_tests(str(root_path))
    if passed:
        return AnalysisReport(
            summary=(
                f"fix 已应用并通过测试：修改了 {len(applied)} 个文件"
                f"（{', '.join(applied)}）。原文件已备份为 .bak。"
            ),
            findings=[Finding(title="修复成功并通过测试", severity="info",
                               detail=f"成功修复 {len(applied)} 个文件，pytest 全部通过。",
                               suggestion="确认无误后可删除 .bak 备份文件。")],
            recommendations=["修复已验证，可安全提交。"],
            confidence="high",
        )

    # —— 测试失败，自动回滚 ——
    print(f"\n测试失败，自动回滚...\n{test_output[-500:]}", file=sys.stderr)
    rolled_back = []
    for fp in applied:
        success = do_rollback(fp)
        if success:
            rolled_back.append(fp)

    return AnalysisReport(
        summary=(
            f"修复已回滚：测试失败，已自动恢复 {len(rolled_back)} 个文件"
            f"（{', '.join(rolled_back)}）。"
        ),
        findings=[
            Finding(title="测试失败，已自动回滚", severity="high",
                     detail=f"修复后测试未通过，已从 .bak 恢复。pytest 输出：\n{test_output[-300:]}",
                     suggestion="请修改 issue 描述后重试，或手动修复。"),
        ],
        recommendations=["检查测试失败原因，调整 issue 描述后重新 fix。"],
        confidence="high",
    )
