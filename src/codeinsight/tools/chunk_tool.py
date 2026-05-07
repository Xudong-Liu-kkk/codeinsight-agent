"""语义分块工具。

用 tree-sitter 解析源码，识别函数和类的边界，
确保 read 工具返回的是完整的语义单元而非被拦腰截断的代码片段。

当前支持 Python / Java / JavaScript / TypeScript / Go 五种语言。
"""

from codeinsight.tools.language_parser import (
    SymbolBoundary,
    get_symbol_boundaries as _get_boundaries,
)


def get_symbol_boundaries(source: str, language: str = "python") -> list[SymbolBoundary]:
    """解析源码，返回所有顶层函数和类的起止行号。

    仅遍历 AST 直接子节点中的函数/类定义，
    嵌套的方法不单独列出（它们的边界包含在外层类中）。

    Args:
        source: 完整源码文本。
        language: 语言名称，默认 'python'。语法未安装时返回空列表。
    """
    return _get_boundaries(source, language)


def expand_to_symbol(
    source: str, target_line: int, language: str = "python"
) -> tuple[int, int] | None:
    """将目标行号扩展到其所在符号的完整边界。

    如果 target_line 落在某个函数或类内部，返回该符号的 (start, end)。
    如果落在所有符号外部（模块级代码），返回 None。
    """
    boundaries = get_symbol_boundaries(source, language)
    for b in boundaries:
        if b.start_line <= target_line <= b.end_line:
            return b.start_line, b.end_line
    return None


def smart_read_range(
    source: str, start_line: int, end_line: int | None, language: str = "python"
) -> tuple[int, int]:
    """计算智能读取范围，确保不截断函数或类。

    规则：
      1. 起始行向上扩展到最近的符号边界
      2. 结束行向下扩展到最近的符号边界
      3. 如果没有符号边界，保持原始范围
      4. 如果起始行在符号外，保持原始起始行

    Args:
        source: 文件完整源码。
        start_line: 用户请求的起始行号（1-based）。
        end_line: 用户请求的结束行号（None 表示文件末尾）。
        language: 语言名称，默认 'python'。

    Returns:
        (expanded_start, expanded_end)，均为 1-based 行号。
    """
    total_lines = len(source.splitlines())
    if end_line is None:
        end_line = total_lines
    end_line = min(end_line, total_lines)

    boundaries = get_symbol_boundaries(source, language)
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
