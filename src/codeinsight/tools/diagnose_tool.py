"""错误诊断工具。

本模块负责从 Python traceback 文本中提取结构化线索，
供引擎层进一步读取源码片段并生成诊断报告。
"""

from dataclasses import dataclass
from pathlib import Path
import re


# TRACEBACK_FRAME_PATTERN 用于匹配标准 Python traceback 中的栈帧行。
TRACEBACK_FRAME_PATTERN = re.compile(r'^\s*File "(?P<file_path>.+?)", line (?P<line_number>\d+), in (?P<function>.+)$')
# EXCEPTION_PATTERN 用于匹配 traceback 最后一行的异常类型与消息。
EXCEPTION_PATTERN = re.compile(r"^(?P<type>[A-Za-z_][\w.]*):\s*(?P<message>.*)$")


@dataclass(slots=True)
class TracebackFrame:
    """单个 traceback 栈帧。"""

    # file_path 为 traceback 中记录的文件路径。
    file_path: str
    # line_number 为异常关联的源码行号。
    line_number: int
    # function 为 traceback 中显示的函数名或模块位置。
    function: str


@dataclass(slots=True)
class TracebackInfo:
    """解析后的 traceback 信息。"""

    # frames 保存按出现顺序提取出的栈帧。
    frames: list[TracebackFrame]
    # exception_type 表示异常类型，例如 ValueError。
    exception_type: str | None
    # exception_message 表示异常消息文本。
    exception_message: str | None


@dataclass(slots=True)
class TracebackSource:
    """诊断输入来源。"""

    # text 为最终用于解析的错误文本。
    text: str
    # source_label 为来源说明，便于报告中展示。
    source_label: str


def load_traceback_source(text: str | None = None, traceback_file: str | None = None) -> TracebackSource:
    """读取诊断输入文本。"""

    # has_text/has_file 用于校验用户是否传入了唯一输入来源。
    has_text = bool(text and text.strip())
    has_file = bool(traceback_file and traceback_file.strip())
    if has_text == has_file:
        raise ValueError("请且仅请提供 --text 或 --traceback-file 其中一种诊断输入。")

    if has_text:
        return TracebackSource(text=text.strip(), source_label="命令行文本")

    # file_path 是存放 traceback 的本地文本文件。
    file_path = Path(traceback_file or "").expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        raise ValueError(f"traceback 文件不存在或不可读：{file_path}")
    try:
        return TracebackSource(text=file_path.read_text(encoding="utf-8").strip(), source_label=str(file_path))
    except UnicodeDecodeError as exc:
        raise ValueError("traceback 文件不是有效的 UTF-8 文本。") from exc


def parse_python_traceback(traceback_text: str) -> TracebackInfo:
    """解析 Python traceback，提取栈帧和异常信息。"""

    # frames 保存所有匹配到的 traceback 栈帧。
    frames: list[TracebackFrame] = []
    # non_empty_lines 用于从尾部寻找异常摘要行。
    non_empty_lines = [line.strip() for line in traceback_text.splitlines() if line.strip()]
    for raw_line in traceback_text.splitlines():
        match = TRACEBACK_FRAME_PATTERN.match(raw_line)
        if not match:
            continue
        frames.append(
            TracebackFrame(
                file_path=match.group("file_path"),
                line_number=int(match.group("line_number")),
                function=match.group("function").strip(),
            )
        )

    # exception_type/message 默认为 None，兼容非标准错误文本。
    exception_type: str | None = None
    exception_message: str | None = None
    for line in reversed(non_empty_lines):
        if line.startswith("Traceback ") or line.startswith("File "):
            continue
        match = EXCEPTION_PATTERN.match(line)
        if match:
            exception_type = match.group("type")
            exception_message = match.group("message")
            break

    return TracebackInfo(frames=frames, exception_type=exception_type, exception_message=exception_message)
