"""符号索引模块。

用 tree-sitter 在项目启动时预扫描所有源码文件，提取函数和类的
名称、文件路径和行号边界，建成轻量符号索引。

搜索命中时直接返回完整函数/类定义，而非单行文本片段。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SymbolInfo:
    """索引中单条符号信息。

    Attributes:
        name: 符号名称（函数名或类名）。
        file_path: 相对于项目根目录的文件路径。
        kind: 符号类型，'function' 或 'class'。
        start_line: 符号起始行号（1-based）。
        end_line: 符号结束行号（1-based）。
    """

    name: str
    file_path: str
    kind: str
    start_line: int
    end_line: int


def build_symbol_index(
    project_root: Path,
) -> dict[str, list[SymbolInfo]]:
    """扫描项目目录，为所有支持的文件建立符号索引。

    遍历项目根目录下的所有文件，对语言支持的文件用 tree-sitter
    提取顶层函数和类，按符号名建立倒排索引。

    Args:
        project_root: 项目根目录。

    Returns:
        {符号名: [SymbolInfo, ...]}，按文件名字母序排列。
    """
    from codeinsight.tools.language_parser import detect_language, get_symbol_boundaries

    index: dict[str, list[SymbolInfo]] = {}

    for dirpath, dirnames, filenames in __import__("os").walk(project_root):
        # 跳过隐藏目录和常见无关目录。
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in ("__pycache__", ".venv", "node_modules", "target", "vendor")
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            full_path = Path(dirpath) / filename
            rel_path = str(full_path.relative_to(project_root))

            language = detect_language(rel_path)
            if language is None:
                continue

            try:
                source = full_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            boundaries = get_symbol_boundaries(source, language)
            for b in boundaries:
                info = SymbolInfo(
                    name=b.name,
                    file_path=rel_path,
                    kind=b.kind,
                    start_line=b.start_line,
                    end_line=b.end_line,
                )
                index.setdefault(b.name, []).append(info)

    # 按文件名字母序排列，保证稳定输出。
    for name in index:
        index[name].sort(key=lambda x: x.file_path)

    return index


def search_symbol_index(
    index: dict[str, list[SymbolInfo]], symbol_name: str
) -> list[SymbolInfo]:
    """在符号索引中搜索。

    支持精确匹配和部分匹配（符号名包含搜索词即可），
    不区分大小写。

    Args:
        index: 符号索引。
        symbol_name: 要搜索的符号名。

    Returns:
        匹配的 SymbolInfo 列表，按文件名字母序排列。
    """
    # 精确匹配优先。
    if symbol_name in index:
        return index[symbol_name]

    # 大小写不敏感匹配。
    lower_name = symbol_name.lower()
    results: list[SymbolInfo] = []
    for name, infos in index.items():
        if lower_name == name.lower():
            results.extend(infos)
            break

    if results:
        return sorted(results, key=lambda x: x.file_path)

    # 部分匹配：搜索词包含在符号名中。
    for name, infos in index.items():
        if lower_name in name.lower():
            results.extend(infos)

    return sorted(results, key=lambda x: x.file_path)
