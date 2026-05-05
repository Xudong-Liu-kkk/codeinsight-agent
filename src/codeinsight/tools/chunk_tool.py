"""语义分块工具。

用 AST 解析 Python 源码，识别函数和类的边界，
确保 read 工具返回的是完整的语义单元而非被拦腰截断的代码片段。
"""

import ast
from dataclasses import dataclass


@dataclass(slots=True)
class SymbolBoundary:
    """一个函数或类的边界信息。"""

    name: str
    kind: str  # "function" | "class"
    start_line: int  # def/class 所在行
    end_line: int  # 符号结束行


def get_symbol_boundaries(source: str) -> list[SymbolBoundary]:
    """解析 Python 源码，返回所有顶层函数和类的起止行号。

    遍历 AST 只取模块直接子节点中的 FunctionDef 和 ClassDef，
    嵌套的类方法不单独列出（它们的边界包含在外层类中）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    boundaries: list[SymbolBoundary] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            boundaries.append(SymbolBoundary(
                name=node.name,
                kind="function",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            ))
        elif isinstance(node, ast.ClassDef):
            boundaries.append(SymbolBoundary(
                name=node.name,
                kind="class",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            ))
    return boundaries


def expand_to_symbol(source: str, target_line: int) -> tuple[int, int] | None:
    """将目标行号扩展到其所在函数的完整边界。

    如果 target_line 落在某个函数或类内部，返回该符号的 (start, end)。
    如果落在所有符号外部（模块级代码），返回 None。
    """
    boundaries = get_symbol_boundaries(source)
    for b in boundaries:
        if b.start_line <= target_line <= b.end_line:
            return b.start_line, b.end_line
    return None


def smart_read_range(source: str, start_line: int, end_line: int | None) -> tuple[int, int]:
    """计算智能读取范围，确保不截断函数或类。

    规则：
      1. 起始行向上扩展到最近的符号边界
      2. 结束行向下扩展到最近的符号边界
      3. 如果没有符号边界，保持原始范围
      4. 如果起始行在符号外，保持原始起始行

    Args:
        source: Python 文件完整源码。
        start_line: 用户请求的起始行号（1-based）。
        end_line: 用户请求的结束行号（None 表示文件末尾）。

    Returns:
        (expanded_start, expanded_end)，均为 1-based 行号。
    """
    total_lines = len(source.splitlines())
    if end_line is None:
        end_line = total_lines
    end_line = min(end_line, total_lines)

    boundaries = get_symbol_boundaries(source)
    if not boundaries:
        return start_line, end_line

    # 向上扩展：找起始行落在哪个符号内，延伸到该符号开头。
    new_start = start_line
    for b in boundaries:
        if b.start_line <= start_line <= b.end_line:
            new_start = b.start_line
            break

    # 向下扩展：找结束行落在哪个符号内，延伸到该符号结尾。
    new_end = end_line
    for b in boundaries:
        if b.start_line <= end_line <= b.end_line:
            new_end = b.end_line
            break

    return new_start, new_end
