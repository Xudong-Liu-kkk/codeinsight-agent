"""错误诊断工具。

本模块负责从 Python traceback / Java stack trace / JS Error 堆栈中
提取结构化线索，供引擎层进一步读取源码片段并生成诊断报告。
"""

from dataclasses import dataclass
from pathlib import Path
import re


# TRACEBACK_FRAME_PATTERN 用于匹配标准 Python traceback 中的栈帧行。
TRACEBACK_FRAME_PATTERN = re.compile(r'^\s*File "(?P<file_path>.+?)", line (?P<line_number>\d+), in (?P<function>.+)$')
# EXCEPTION_PATTERN 用于匹配 traceback 最后一行的异常类型与消息。
EXCEPTION_PATTERN = re.compile(r"^(?P<type>[A-Za-z_][\w.]*):\s*(?P<message>.*)$")

# Java 堆栈行：at com.foo.Bar.method(Bar.java:42)  或 at com.foo.Bar.main(Bar.java:15)（无方法名）。
JAVA_FRAME_PATTERN = re.compile(
    r"^\s*at\s+(?P<class>[a-zA-Z_$][\w.$]+)"
    r"(?:\.(?P<method>[\w$<>]+))?"
    r"\((?P<file>[^)]+\.java):(?P<line>\d+)\)"
)
# Java 异常头：Exception in thread "..." com.foo.SomeException: message
JAVA_EXCEPTION_PATTERN = re.compile(
    r"(?:Exception in thread|Caused by):\s*(?P<type>[\w.]+Exception[\w.]*):?\s*(?P<message>.*)"
)

# JS/TS 堆栈行：at funcName (/path/to/file.js:10:5)
JS_FRAME_PATTERN = re.compile(
    r"^\s*at\s+(?P<function>[^(]+?)\s+\((?P<file>[^)]+\.(?:js|ts|jsx|tsx|mjs)):(?P<line>\d+):(?P<col>\d+)\)"
)
# JS 简洁格式：at /path/to/file.js:10:5（匿名函数无方法名）。
JS_ANON_FRAME_PATTERN = re.compile(
    r"^\s*at\s+(?P<file>[^(]+\.(?:js|ts|jsx|tsx|mjs)):(?P<line>\d+):(?P<col>\d+)\)?"
)
# JS 异常头：TypeError: message  或 ReferenceError: message
JS_EXCEPTION_PATTERN = re.compile(r"^(?P<type>[A-Za-z_]\w*(?:Error|Exception)):\s*(?P<message>.*)$")


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


# —— Java 堆栈解析 ——


def parse_java_stacktrace(text: str) -> TracebackInfo:
    """解析 Java 堆栈信息，提取栈帧和异常类型。

    支持标准 JVM 异常格式：
        Exception in thread "main" java.lang.NullPointerException: message
            at com.example.App.process(App.java:42)
            at com.example.App.main(App.java:15)
    """
    frames: list[TracebackFrame] = []
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in text.splitlines():
        match = JAVA_FRAME_PATTERN.match(line)
        if not match:
            continue
        file_name = match.group("file")
        line_num = int(match.group("line"))
        method = match.group("method") or match.group("class").rsplit(".", 1)[-1]
        frames.append(
            TracebackFrame(
                file_path=file_name,
                line_number=line_num,
                function=f"{match.group('class')}.{method}",
            )
        )

    exception_type: str | None = None
    exception_message: str | None = None
    for line in non_empty_lines:
        java_match = JAVA_EXCEPTION_PATTERN.match(line)
        if java_match:
            exception_type = java_match.group("type").rsplit(".", 1)[-1]
            exception_message = java_match.group("message") or ""
            break

    return TracebackInfo(frames=frames, exception_type=exception_type, exception_message=exception_message)


# —— JS/TS 错误堆栈解析 ——


def parse_js_stacktrace(text: str) -> TracebackInfo:
    """解析 JavaScript/TypeScript 错误堆栈，提取栈帧和异常类型。

    支持标准 V8 引擎 Error 格式：
        TypeError: Cannot read property 'foo' of null
            at processFile (/path/to/file.js:10:5)
            at /path/to/file.js:20:1
    """
    frames: list[TracebackFrame] = []
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in text.splitlines():
        named_match = JS_FRAME_PATTERN.match(line)
        if named_match:
            frames.append(
                TracebackFrame(
                    file_path=named_match.group("file"),
                    line_number=int(named_match.group("line")),
                    function=named_match.group("function").strip(),
                )
            )
        else:
            anon_match = JS_ANON_FRAME_PATTERN.match(line)
            if anon_match:
                frames.append(
                    TracebackFrame(
                        file_path=anon_match.group("file"),
                        line_number=int(anon_match.group("line")),
                        function="<anonymous>",
                    )
                )

    exception_type: str | None = None
    exception_message: str | None = None
    for line in non_empty_lines:
        if line.startswith("at "):
            continue
        js_match = JS_EXCEPTION_PATTERN.match(line)
        if js_match:
            exception_type = js_match.group("type")
            exception_message = js_match.group("message")
            break

    return TracebackInfo(frames=frames, exception_type=exception_type, exception_message=exception_message)


# —— 自动检测并解析 ——


def parse_error(error_text: str) -> TracebackInfo:
    """自动检测错误文本格式并解析。

    检测优先级：
      1. Python traceback（包含 `File "...` 或 `Traceback` 行）
      2. Java stack trace（包含 `at ` 行和 `.java:` 引用）
      3. JS/TS Error stack（包含 `at ` 行和 `.js:` / `.ts:` 引用）
      4. 兜底：尝试按 Python 格式解析（兼容未识别的错误消息）

    Args:
        error_text: 完整的错误文本。

    Returns:
        解析后的 TracebackInfo。
    """
    # 检测 Python：特征为 `File "...", line N, in func` 或 `Traceback` 开头。
    if "File \"" in error_text or error_text.strip().startswith("Traceback"):
        return parse_python_traceback(error_text)

    # 检测 Java：特征为 `at xxx.xxx.xxx(Xxx.java:N)`。
    if ".java:" in error_text and "at " in error_text:
        return parse_java_stacktrace(error_text)

    # 检测 JS/TS：特征为 `at func (xxx.js:N:M)` 或 `at xxx.ts:N:M`。
    js_exts = (".js:", ".ts:", ".jsx:", ".tsx:", ".mjs:")
    if any(ext in error_text for ext in js_exts) and "at " in error_text:
        return parse_js_stacktrace(error_text)

    # 兜底：尝试 Python 格式。
    return parse_python_traceback(error_text)


# —— 多语言异常建议 ——

# 补充 Java 和 JS 通用错误的排查建议。
EXCEPTION_ADVICE.update({
    "NullPointerException": (
        "空指针异常。排查步骤：1) 确认调用链中哪个变量为 null；"
        "2) 检查对象初始化是否被跳过（条件分支、延迟加载失败）；"
        "3) 对可能为 null 的返回值添加 null 检查或用 Optional 包装；"
        "4) 查看堆栈中最后一行自己的代码，向上追溯 null 来源。"
    ),
    "ArrayIndexOutOfBoundsException": (
        "数组索引越界。排查步骤：1) 检查循环边界条件是否正确；"
        "2) 确认数组长度和访问索引的关系（索引从 0 开始）；"
        "3) 对动态索引来源（方法参数、计算结果）增加范围校验。"
    ),
    "ClassNotFoundException": (
        "类未找到。排查步骤：1) 确认类名拼写正确（包含完整包名）；"
        "2) 检查依赖是否在 pom.xml / build.gradle 中声明；"
        "3) 确认 JAR 文件是否在 classpath 中。"
    ),
    "JavaIOException": (
        "IO 异常。排查步骤：1) 确认文件路径是否正确；"
        "2) 检查文件权限（是否可读/可写）；3) 确认文件未被其他进程锁定。"
    ),
    "NodeError": (
        "Node.js 错误。排查步骤：1) 检查模块路径是否正确；"
        "2) 确认依赖已安装（npm install）；3) 检查文件权限和端口占用。"
    ),
    "SyntaxError": (
        "语法错误。排查步骤：1) 检查错误提示行的括号、引号是否闭合；"
        "2) 确认使用了正确的语法版本（ES6 vs CommonJS）；"
        "3) 对 JSX/TSX 文件确认转译工具配置正确。"
    ),
    "ReferenceError": (
        "引用错误。排查步骤：1) 确认变量名拼写正确（包括大小写）；"
        "2) 检查变量是否在当前作用域内定义；"
        "3) 确认 import / require 语句正确导出了所需符号。"
    ),
    "TypeError_JS": (
        "JS 类型错误。排查步骤：1) 检查是否对 undefined/null 调用了方法；"
        "2) 确认回调函数的参数顺序是否正确；"
        "3) 使用 typeof 校验变量类型后再操作。"
    ),
})
