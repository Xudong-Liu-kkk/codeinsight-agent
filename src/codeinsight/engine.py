"""V1 骨架阶段的核心命令处理函数。

当前实现优先保证“行为稳定 + 输出结构稳定”。
后续批次会逐步替换为真实工具调用，但对外报告协议保持不变。
"""

from pathlib import Path

from codeinsight.schemas import AnalysisReport, CodeEvidence, Finding
from codeinsight.tools import get_exception_advice, list_project_tree, load_traceback_source, parse_python_traceback, parse_pyproject_deps, read_file_lines, search_code


def run_overview(root: str) -> AnalysisReport:
    """生成项目概览报告（骨架版本）。

    参数:
        root: 需要分析的项目根目录路径。

    返回:
        AnalysisReport: 统一结构化报告对象。
    """

    # 将用户输入路径规范化为绝对路径，减少路径歧义。
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
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

    try:
        # tree_summary 是目录树扫描后的统计与样例结果。
        tree_summary = list_project_tree(root_path, max_depth=3)
    except ValueError as exc:
        return AnalysisReport(
            summary=f"项目概览失败：{exc}",
            findings=[
                Finding(
                    title="目录扫描失败",
                    severity="high",
                    detail=str(exc),
                    suggestion="请检查目录权限或路径后重试。",
                )
            ],
            recommendations=["确认项目目录可访问。"],
            confidence="high",
        )

    # tree_preview 为目录树样例文本，便于终端快速预览项目结构。
    tree_preview = "\n".join(tree_summary.sampled_lines[:12])
    return AnalysisReport(
        summary="已生成真实项目概览（第二批工具层）。",
        findings=[
            Finding(
                title="目录统计完成",
                severity="info",
                detail=f"检测到目录 {tree_summary.total_dirs} 个，文件 {tree_summary.total_files} 个。",
                suggestion="如需更详细定位，可继续使用 `search` 命令。",
            )
        ],
        evidence=[
            CodeEvidence(
                file_path=str(root_path),
                start_line=1,
                end_line=len(tree_summary.sampled_lines[:12]),
                snippet=tree_preview,
                reason="目录树样例可作为项目结构分析证据。",
            )
        ],
        recommendations=["先关注顶层目录，再逐步下钻到核心模块。"],
        confidence="high",
    )


def run_search(root: str, query: str, glob_pattern: str | None = None) -> AnalysisReport:
    """执行搜索命令（骨架版本）。

    参数:
        root: 搜索根目录路径。
        query: 用户输入的关键词或符号。

    返回:
        AnalysisReport: 统一结构化报告对象。
    """

    # root_path 表示规范化后的搜索根目录路径。
    root_path = Path(root).resolve()
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

    try:
        # hits 是搜索工具返回的命中结果列表。
        hits = search_code(root_path, query, glob_pattern=glob_pattern, max_hits=30)
    except ValueError as exc:
        return AnalysisReport(
            summary=f"搜索失败：{exc}",
            findings=[
                Finding(
                    title="搜索参数或路径无效",
                    severity="high",
                    detail=str(exc),
                    suggestion="检查 --root 路径和搜索参数后重试。",
                )
            ],
            recommendations=["确认项目目录存在且可访问。"],
            confidence="high",
        )
    except RuntimeError as exc:
        return AnalysisReport(
            summary=f"搜索工具执行异常：{exc}",
            findings=[
                Finding(
                    title="搜索执行异常",
                    severity="high",
                    detail=str(exc),
                    suggestion="请稍后重试，或检查本地搜索工具环境。",
                )
            ],
            recommendations=["如未安装 rg，可继续使用 Python 回退搜索。"],
            confidence="medium",
        )

    if not hits:
        return AnalysisReport(
            summary="未检索到匹配结果。",
            findings=[
                Finding(
                    title="未命中任何结果",
                    severity="info",
                    detail=f"关键词 {query!r} 在当前范围内未匹配到内容。",
                    suggestion="可尝试缩短关键词、调整大小写或使用 --glob 限定文件类型。",
                )
            ],
            recommendations=["示例：`--glob \"*.py\" --query \"run_search\"`"],
            confidence="high",
        )

    # evidence_list 将搜索命中映射为统一证据结构，便于后续统一展示。
    evidence_list: list[CodeEvidence] = [
        CodeEvidence(
            file_path=hit.file_path,
            start_line=hit.line_number,
            end_line=hit.line_number,
            snippet=hit.line_text,
            reason="关键词命中行可直接支撑搜索结论。",
        )
        for hit in hits
    ]
    return AnalysisReport(
        summary=f"已完成搜索，命中 {len(hits)} 条结果。",
        findings=[
            Finding(
                title="搜索执行成功",
                severity="info",
                detail=f"关键词 {query!r} 已在项目内完成检索。",
                suggestion="可结合 evidence 继续定位上下文代码。",
            )
        ],
        evidence=evidence_list,
        recommendations=["如需收敛范围，可增加 `--glob \"*.py\"`。"],
        confidence="high",
    )


def run_deps(root: str) -> AnalysisReport:
    """分析项目依赖配置并生成报告。"""

    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"依赖分析失败：项目根目录不存在：{root_path}",
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

    try:
        deps_result = parse_pyproject_deps(root_path)
    except FileNotFoundError as exc:
        return AnalysisReport(
            summary=f"依赖分析失败：{exc}",
            findings=[
                Finding(
                    title="pyproject.toml 不存在",
                    severity="high",
                    detail=str(exc),
                    suggestion="当前仅支持解析 pyproject.toml 格式的 Python 项目依赖。",
                )
            ],
            recommendations=["在项目根目录创建 pyproject.toml 后重试。"],
            confidence="high",
        )
    except Exception as exc:
        return AnalysisReport(
            summary=f"依赖分析失败：{exc}",
            findings=[
                Finding(
                    title="依赖配置解析失败",
                    severity="high",
                    detail=str(exc),
                    suggestion="请检查 pyproject.toml 格式是否正确。",
                )
            ],
            recommendations=["确认 pyproject.toml 符合 PEP 621 规范。"],
            confidence="high",
        )

    findings: list[Finding] = []
    evidence_list: list[CodeEvidence] = []

    # 运行时依赖统计。
    runtime_names = [dep.name for dep in deps_result.runtime_deps]
    if runtime_names:
        findings.append(
            Finding(
                title=f"运行时依赖（{deps_result.total_runtime} 个）",
                severity="info",
                detail=f"依赖项：{', '.join(runtime_names)}",
                suggestion="确认所有运行时依赖均为项目实际所需。",
            )
        )
    else:
        findings.append(
            Finding(
                title="无运行时依赖",
                severity="medium",
                detail="pyproject.toml 中未声明 runtime 依赖。",
                suggestion="纯工具项目或无外部依赖时这属于正常情况。",
            )
        )

    # 开发依赖统计。
    dev_names = [dep.name for dep in deps_result.dev_deps]
    if dev_names:
        findings.append(
            Finding(
                title=f"开发依赖（{deps_result.total_dev} 个）",
                severity="info",
                detail=f"依赖项：{', '.join(dev_names)}",
                suggestion="开发依赖不会被最终用户安装，仅影响开发环境。",
            )
        )

    # 锁文件检查。
    if deps_result.has_lock_file:
        findings.append(
            Finding(
                title="锁文件存在",
                severity="info",
                detail=f"已检测到 {deps_result.lock_file_path}，项目依赖已锁定。",
                suggestion="定期更新锁文件以获取安全补丁。",
            )
        )
    else:
        findings.append(
            Finding(
                title="锁文件缺失",
                severity="high",
                detail="未检测到 uv.lock 或类似锁文件。",
                suggestion="运行 `uv lock` 生成锁文件，确保可复现构建。",
            )
        )

    # 将依赖列表作为证据。
    if runtime_names:
        evidence_list.append(
            CodeEvidence(
                file_path=str(root_path / "pyproject.toml"),
                start_line=1,
                end_line=1,
                snippet="\n".join(f"{dep.name} {dep.version_spec}" for dep in deps_result.runtime_deps),
                reason="运行时依赖列表。",
            )
        )

    return AnalysisReport(
        summary=(
            f"依赖分析完成：运行时 {deps_result.total_runtime} 个，"
            f"开发 {deps_result.total_dev} 个，"
            f"锁文件{'已' if deps_result.has_lock_file else '未'}检测到。"
        ),
        findings=findings,
        evidence=evidence_list,
        recommendations=[
            "保持依赖最小化，避免引入不必要的第三方库。",
            "定期检查依赖是否存在已知漏洞。",
            "锁文件应纳入版本管理以确保可复现构建。",
        ],
        confidence="high",
    )


def run_read(
    root: str,
    file_path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 300,
) -> AnalysisReport:
    """读取项目内安全文件片段并生成报告。"""

    # root_path 表示规范化后的项目根目录。
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"读取失败：项目根目录不存在：{root_path}",
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
            summary="读取失败：文件路径为空。",
            findings=[
                Finding(
                    title="文件路径为空",
                    severity="medium",
                    detail="read 命令要求 --path 必须是非空字符串。",
                    suggestion="请传入相对于 --root 的文件路径。",
                )
            ],
            recommendations=["示例：`read --path src/codeinsight/engine.py --start 1 --end 40`"],
            confidence="high",
        )

    try:
        # read_result 是文件读取工具返回的安全片段。
        read_result = read_file_lines(
            root_path,
            file_path,
            start_line=start_line,
            end_line=end_line,
            max_lines=max_lines,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return AnalysisReport(
            summary=f"读取失败：{exc}",
            findings=[
                Finding(
                    title="文件读取失败",
                    severity="high",
                    detail=str(exc),
                    suggestion="请检查路径是否位于项目内、文件是否为 UTF-8 文本，并确认不是敏感文件。",
                )
            ],
            recommendations=["使用 search 命令先定位文件，再用 read 命令读取片段。"],
            confidence="high",
        )

    return AnalysisReport(
        summary=f"已读取文件片段：{read_result.file_path}:{read_result.start_line}-{read_result.end_line}。",
        findings=[
            Finding(
                title="文件读取成功",
                severity="info",
                detail=(
                    f"返回第 {read_result.start_line} 到 {read_result.end_line} 行。"
                    f"{' 内容已按最大行数截断。' if read_result.truncated else ''}"
                ),
                suggestion="可结合 search 命令继续定位其他相关代码。",
            )
        ],
        evidence=[
            CodeEvidence(
                file_path=read_result.file_path,
                start_line=read_result.start_line,
                end_line=read_result.end_line,
                snippet=read_result.content,
                reason="用户显式请求读取该文件片段。",
            )
        ],
        recommendations=["保持读取范围尽量小，优先查看与问题相关的上下文。"],
        confidence="high",
    )


def run_diagnose(root: str, text: str | None = None, traceback_file: str | None = None) -> AnalysisReport:
    """根据 Python traceback 或错误文本生成诊断报告。"""

    # root_path 表示规范化后的项目根目录。
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return AnalysisReport(
            summary=f"诊断失败：项目根目录不存在：{root_path}",
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

    try:
        # source 是规范化后的诊断输入来源。
        source = load_traceback_source(text=text, traceback_file=traceback_file)
    except ValueError as exc:
        return AnalysisReport(
            summary=f"诊断输入无效：{exc}",
            findings=[
                Finding(
                    title="诊断输入无效",
                    severity="medium",
                    detail=str(exc),
                    suggestion="请使用 --text 或 --traceback-file 提供一份错误文本。",
                )
            ],
            recommendations=["示例：`diagnose --text \"ValueError: bad value\"`"],
            confidence="high",
        )

    # traceback_info 是从错误文本中解析出的结构化线索。
    traceback_info = parse_python_traceback(source.text)
    # evidence_list 保存根据 traceback 栈帧读取到的源码证据。
    evidence_list: list[CodeEvidence] = []
    # skipped_frames 统计因越界、敏感文件或不可读而跳过的栈帧数量。
    skipped_frames = 0
    for frame in traceback_info.frames[-5:]:
        frame_path = Path(frame.file_path)
        # relative_path 用于兼容绝对路径和相对路径两种 traceback 形态。
        relative_path = frame_path
        if frame_path.is_absolute():
            try:
                relative_path = frame_path.resolve().relative_to(root_path)
            except ValueError:
                skipped_frames += 1
                continue
        try:
            read_result = read_file_lines(
                root_path,
                str(relative_path),
                start_line=frame.line_number - 5,
                end_line=frame.line_number + 5,
                max_lines=11,
            )
        except ValueError:
            skipped_frames += 1
            continue
        evidence_list.append(
            CodeEvidence(
                file_path=read_result.file_path,
                start_line=read_result.start_line,
                end_line=read_result.end_line,
                snippet=read_result.content,
                reason=f"traceback 指向函数 {frame.function!r} 的第 {frame.line_number} 行。",
            )
        )

    # exception_title 根据是否解析到异常类型生成更具体的标题。
    exception_title = traceback_info.exception_type or "未识别异常类型"
    exception_message = traceback_info.exception_message or "未提取到明确异常消息。"
    findings = [
        Finding(
            title=f"异常类型：{exception_title}",
            severity="high" if traceback_info.exception_type else "medium",
            detail=f"输入来源：{source.source_label}；异常消息：{exception_message}",
            suggestion="优先查看最后一个项目内栈帧附近的源码和调用参数。",
        )
    ]

    # 如果识别到常见异常类型，附加专项排查建议。
    exception_advice = get_exception_advice(exception_title)
    if exception_advice:
        findings.append(
            Finding(
                title=f"{exception_title} 专项排查建议",
                severity="info",
                detail=exception_advice,
                suggestion="按步骤逐一排查，通常前两项就能定位根因。",
            )
        )
    if skipped_frames:
        findings.append(
            Finding(
                title="部分栈帧未读取",
                severity="info",
                detail=f"有 {skipped_frames} 个栈帧位于项目外、敏感路径或不可读文件中。",
                suggestion="这是只读安全策略的预期行为，可重点关注已返回的项目内证据。",
            )
        )
    if not traceback_info.frames:
        findings.append(
            Finding(
                title="未检测到标准 Python traceback 栈帧",
                severity="medium",
                detail="输入文本中没有匹配到 `File ..., line ...` 形式的栈帧。",
                suggestion="请粘贴完整 traceback，或使用 search 命令搜索异常文本。",
            )
        )

    return AnalysisReport(
        summary=f"已完成错误诊断：{exception_title}。",
        findings=findings,
        evidence=evidence_list,
        recommendations=[
            "从最后一个项目内栈帧开始排查，因为它通常最接近真实出错位置。",
            "检查异常行附近的变量是否可能为空、路径是否存在、类型是否符合预期。",
            "如果证据为空，请确认 traceback 中的文件路径位于 --root 指定的项目目录内。",
        ],
        confidence="high" if evidence_list else "medium",
    )
