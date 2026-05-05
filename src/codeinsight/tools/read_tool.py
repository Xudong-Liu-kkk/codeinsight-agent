"""文件读取工具。"""

from dataclasses import dataclass
from pathlib import Path

from codeinsight.tools.path_guard import guard_readable_path


@dataclass(slots=True)
class ReadResult:
    """文件读取结果。"""

    # file_path 表示实际读取到的文件路径。
    file_path: str
    # start_line 表示返回内容的起始行号（闭区间）。
    start_line: int
    # end_line 表示返回内容的结束行号（闭区间）。
    end_line: int
    # content 是拼接后的文本内容。
    content: str
    # truncated 表示是否因 max_lines 限制被截断。
    truncated: bool


def read_file_lines(
    root: Path,
    file_path: str,
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 300,
) -> ReadResult:
    """按行读取文件内容，并执行安全与长度限制。"""

    # target_path 是用户请求读取的目标路径对象。
    target_path = Path(file_path)
    # safe_path 是通过安全校验后的可读路径。
    safe_path = guard_readable_path(root, root / target_path)
    if not safe_path.exists() or not safe_path.is_file():
        raise ValueError(f"文件不存在或不可读：{safe_path}")

    # 读取文件全文，支持语义分块。
    raw_text = safe_path.read_text(encoding="utf-8")
    lines = raw_text.splitlines()

    # normalized_start 对起始行号做下限保护。
    normalized_start = max(1, start_line)
    # normalized_end 为结束行号，未传则默认到文件末尾。
    normalized_end = len(lines) if end_line is None else min(len(lines), end_line)
    if normalized_start > normalized_end:
        raise ValueError("读取行区间无效：起始行大于结束行。")

    # Python 文件：用 AST 语义分块，确保不截断函数/类。
    if safe_path.suffix == ".py" and end_line is not None:
        from codeinsight.tools.chunk_tool import smart_read_range
        expanded_start, expanded_end = smart_read_range(raw_text, normalized_start, normalized_end)
        # 如果扩展后仍在可接受范围内（不超过 2 倍 max_lines），应用扩展。
        if expanded_end - expanded_start <= max_lines * 2:
            normalized_start, normalized_end = expanded_start, expanded_end

    # selected_lines 为按区间切出的原始内容。
    selected_lines = lines[normalized_start - 1 : normalized_end]
    # truncated 标识是否触发最大行数截断。
    truncated = len(selected_lines) > max_lines
    if truncated:
        selected_lines = selected_lines[:max_lines]
        normalized_end = normalized_start + max_lines - 1

    # content 将行列表拼接为标准文本。
    content = "\n".join(selected_lines)
    return ReadResult(
        file_path=str(safe_path),
        start_line=normalized_start,
        end_line=normalized_end,
        content=content,
        truncated=truncated,
    )

