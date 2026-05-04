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


# 常见异常类型的专门排查建议。
EXCEPTION_ADVICE: dict[str, str] = {
    "ModuleNotFoundError": (
        "模块未找到。排查步骤：1) 确认包名拼写是否正确；"
        "2) 检查 pyproject.toml 或 requirements.txt 是否已声明该依赖；"
        "3) 运行 `uv sync` 或 `pip install` 安装缺失的包；"
        "4) 如果是项目内部模块，检查 `__init__.py` 是否存在或 sys.path 是否包含源码目录。"
    ),
    "ImportError": (
        "导入失败。排查步骤：1) 确认模块路径拼写正确（区分大小写）；"
        "2) 检查是否存在循环导入（A 导入 B，B 又导入 A）；"
        "3) 确认包目录下存在 `__init__.py` 文件；"
        "4) 如果错误消息提示具体符号名，确认该符号确实存在于目标模块中。"
    ),
    "FileNotFoundError": (
        "文件未找到。排查步骤：1) 确认文件路径拼写是否正确；"
        "2) 检查是绝对路径还是相对路径，相对路径的当前工作目录是否符合预期；"
        "3) 确认文件在项目根目录内且未被 .gitignore 排除；"
        "4) 如果路径来自用户输入或配置，检查是否做了必要的路径展开（如 ~ 展开为 HOME 目录）。"
    ),
    "KeyError": (
        "字典键不存在。排查步骤：1) 确认键名拼写正确（区分大小写）；"
        "2) 使用 dict.get() 替代 dict[] 以避免 KeyError；"
        "3) 打印 dict.keys() 确认当前可用的键列表；"
        "4) 如果键来自外部数据（JSON、API 响应），确认数据结构与预期一致。"
    ),
    "AttributeError": (
        "对象属性不存在。排查步骤：1) 确认属性名拼写正确；"
        "2) 检查对象是否为 None（NoneType 没有任何属性）；"
        "3) 使用 type() 或 isinstance() 确认对象类型是否符合预期；"
        "4) 如果对象来自函数返回，确认该函数在所有分支上都返回了正确类型。"
    ),
    "TypeError": (
        "类型错误。排查步骤：1) 确认传入参数的类型是否正确（如 int vs str）；"
        "2) 检查是否对 None 执行了运算操作；"
        "3) 检查函数调用时参数个数是否匹配（多了或少了）；"
        "4) 如果涉及运算符（如 +），确认两个操作数的类型兼容。"
    ),
    "ValueError": (
        "值不合法。排查步骤：1) 确认输入值是否在允许范围内；"
        "2) 检查数据格式是否符合预期（如日期格式、编码格式）；"
        "3) 如果来自用户输入，增加输入校验和友好提示；"
        "4) 查看异常消息中的具体值，定位哪个参数或变量触发了错误。"
    ),
    "NameError": (
        "变量名未定义。排查步骤：1) 确认变量名拼写正确（注意大小写）；"
        "2) 检查变量是否在当前位置之前已被赋值；"
        "3) 确认变量是否在正确的命名空间中（函数内 vs 模块级 vs 全局）；"
        "4) 检查是否有未闭合的函数或条件分支导致变量未被定义。"
    ),
    "IndexError": (
        "索引越界。排查步骤：1) 使用 len() 检查序列长度；"
        "2) 确认索引是从 0 开始还是从 1 开始（后者常见错误）；"
        "3) 在循环中访问 list[index] 前确认 index < len(list)；"
        "4) 考虑使用 for item in sequence 替代按索引遍历以减少越界风险。"
    ),
    "RuntimeError": (
        "运行时错误。排查步骤：1) 仔细阅读异常消息了解具体原因；"
        "2) 检查是否存在无限递归调用导致栈溢出；"
        "3) 检查多线程/多进程环境下是否存在资源竞争；"
        "4) 如果来自第三方库，查看该库的文档和 GitHub Issues。"
    ),
}


def get_exception_advice(exception_type: str | None) -> str | None:
    """根据异常类型返回专门排查建议，未知类型返回 None。"""
    if exception_type is None:
        return None
    return EXCEPTION_ADVICE.get(exception_type)


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
