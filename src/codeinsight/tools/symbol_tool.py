"""符号提取工具。

用 tree-sitter 精确提取源码中指定函数或类的定义范围，
供 review 命令做聚焦审查。支持 Python / Java / JavaScript / TypeScript / Go。
"""

from pathlib import Path

from codeinsight.tools.language_parser import detect_language, find_symbol_source as _find_symbol


def find_symbol_source(file_path: Path, symbol_name: str) -> str | None:
    """从源码文件中提取指定符号（函数或类）的完整源码。

    自动检测文件语言，用 tree-sitter 解析语法树后在模块顶层
    和类内部查找匹配的符号节点。

    Args:
        file_path: 源码文件路径。
        symbol_name: 要查找的函数名或类名。

    Returns:
        提取到的源码文本（含标注头），未找到或语言不支持时返回 None。
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    language = detect_language(file_path)
    if language is None:
        return None

    segment = _find_symbol(source, symbol_name, language)
    if segment is None:
        return None

    # 标注来源信息，方便 LLM 理解上下文。
    return (
        f"# 文件：{file_path}\n"
        f"# 符号：{symbol_name}\n\n"
        f"{segment}"
    )
