"""符号提取工具。

用 ast 模块精确提取 Python 源码中指定函数或类的定义范围，
供 review 命令做聚焦审查。
"""

import ast
from pathlib import Path


def find_symbol_source(file_path: Path, symbol_name: str) -> str | None:
    """从 Python 文件中提取指定符号（函数或类）的完整源码。

    使用 ast 模块解析语法树，在模块顶层和类内部查找匹配的
    FunctionDef 或 ClassDef 节点，然后用 ast.get_source_segment
    从原始源码中提取精确的文本片段。

    Args:
        file_path: Python 源码文件路径。
        symbol_name: 要查找的函数名或类名。

    Returns:
        提取到的源码文本，未找到时返回 None。
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # 在模块顶层和类内部查找匹配的符号。
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol_name:
                segment = ast.get_source_segment(source, node)
                if segment:
                    # 标注来源信息，方便 LLM 理解上下文。
                    return (
                        f"# 文件：{file_path}\n"
                        f"# 符号：{symbol_name}\n\n"
                        f"{segment}"
                    )
                return None

    return None
