"""基于 tree-sitter 的多语言代码解析层。

本模块封装 tree-sitter 调用，为上层工具（chunk_tool、symbol_tool、
agent_tools）提供统一的语言无关 API：符号边界检测、符号源码提取、
import 语句解析。

语法包按需懒加载，未安装的语法静默跳过——不影响已有功能。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


# —— 语言检测 ——

SUFFIX_MAP: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}


def detect_language(file_path: str | Path) -> str | None:
    """根据文件后缀检测编程语言。

    Args:
        file_path: 文件路径（字符串或 Path 对象）。

    Returns:
        语言名称（如 'python'、'java'），不支持时返回 None。
    """
    suffix = Path(file_path).suffix.lower()
    return SUFFIX_MAP.get(suffix)


# —— 节点类型定义 ——
# 每种语言中表示"函数/方法""类/类型""import 语句"的 tree-sitter 节点类型名。

_LANGUAGE_NODE_TYPES: dict[str, dict[str, tuple[str, ...]]] = {
    "python": {
        "functions": ("function_definition",),
        "classes": ("class_definition",),
        "imports": ("import_statement", "import_from_statement"),
    },
    "java": {
        "functions": ("method_declaration", "constructor_declaration"),
        "classes": ("class_declaration", "interface_declaration", "enum_declaration"),
        "imports": ("import_declaration",),
    },
    "javascript": {
        "functions": ("function_declaration", "generator_function_declaration"),
        "classes": ("class_declaration",),
        "imports": ("import_statement",),
    },
    "typescript": {
        "functions": (
            "function_declaration",
            "generator_function_declaration",
            "method_definition",
        ),
        "classes": (
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
        ),
        "imports": ("import_statement",),
    },
    "go": {
        "functions": ("function_declaration", "method_declaration"),
        "classes": ("type_declaration",),
        "imports": ("import_declaration",),
    },
}


# —— 解析器懒加载缓存 ——
# 每个语言首次调用时 import 语法包并构建 Parser，失败则缓存 None。
# 后续调用直接命中缓存，零开销。

_parser_cache: dict[str, Any | None] = {}
_import_error_cache: dict[str, bool] = {}

# 语法包导入路径，按语言名索引。
_GRAMMAR_IMPORTS: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "java": ("tree_sitter_java", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
}


def _get_parser(language: str):
    """获取指定语言的 tree-sitter Parser 实例。

    首次调用时尝试 import 对应语法包，失败则缓存结果避免重复尝试。

    Args:
        language: 语言名称，如 'python'。

    Returns:
        Parser 实例，语法不可用时返回 None。
    """
    if language in _parser_cache:
        return _parser_cache[language]
    if language in _import_error_cache:
        return None

    grammar_entry = _GRAMMAR_IMPORTS.get(language)
    if grammar_entry is None:
        _import_error_cache[language] = True
        return None

    package_name, func_name = grammar_entry
    try:
        grammar_module = __import__(package_name, fromlist=[func_name])
        grammar_func = getattr(grammar_module, func_name)
        from tree_sitter import Language, Parser

        lang = Language(grammar_func())
        parser = Parser(lang)
        _parser_cache[language] = parser
        return parser
    except ImportError:
        _import_error_cache[language] = True
        return None
    except Exception:
        _import_error_cache[language] = True
        return None


def is_semantic_language(file_path: str | Path) -> bool:
    """判断文件是否支持语义分析（语法包已安装）。

    Args:
        file_path: 文件路径。

    Returns:
        True 当文件后缀对应已知语言且对应语法包已安装。
    """
    lang = detect_language(file_path)
    if lang is None:
        return False
    return _get_parser(lang) is not None


# —— SymbolBoundary 数据结构 ——
# 与 chunk_tool.SymbolBoundary 相同，模块内定义避免循环引用。


@dataclass(slots=True)
class SymbolBoundary:
    """一个代码符号（函数或类）的边界信息。

    Attributes:
        name: 符号名称。
        kind: 符号类型，'function' 或 'class'。
        start_line: 符号起始行号（1-based）。
        end_line: 符号结束行号（1-based）。
    """

    name: str
    kind: str
    start_line: int
    end_line: int


# —— 辅助函数 ——


def _get_node_name(node) -> str | None:
    """从 tree-sitter 节点中提取符号名称。

    通过 child_by_field_name("name") 获取名称节点，
    这在 Python/Java/JS/TS/Go 五者中是统一的字段名。
    """
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode("utf-8")
    return None


def _node_source_segment(source: str, node) -> str:
    """从源码中按字节偏移提取节点对应的源代码片段。

    替代 ast.get_source_segment()，对所有语言通用。
    """
    source_bytes = source.encode("utf-8")
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8")


def _iter_child_nodes(root, language: str):
    """遍历根节点的子节点，对 TypeScript 展开 export 包装。

    因为 TypeScript 中 `export function foo()` 会把 function_declaration
    嵌套在 export_statement 内部，需要额外展开一层。
    """
    for child in root.children:
        if language == "typescript" and child.type == "export_statement":
            yield from child.children
        else:
            yield child


# —— 公共 API ——


def get_symbol_boundaries(source: str, language: str = "python") -> list[SymbolBoundary]:
    """获取源码中所有顶层函数和类的边界。

    仅遍历 AST 的直接子节点（顶层符号），不递归进入函数体或类体内部。

    Args:
        source: 完整源码文本。
        language: 语言名称，默认 'python'。

    Returns:
        SymbolBoundary 列表，语法不可用或解析失败时返回空列表。
    """
    parser = _get_parser(language)
    if parser is None:
        return []

    try:
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return []

    node_types = _LANGUAGE_NODE_TYPES.get(language, {})
    function_types = node_types.get("functions", ())
    class_types = node_types.get("classes", ())

    boundaries: list[SymbolBoundary] = []
    for child in _iter_child_nodes(tree.root_node, language):
        if child.type in function_types:
            name = _get_node_name(child)
            if name:
                boundaries.append(
                    SymbolBoundary(
                        name=name,
                        kind="function",
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                    )
                )
        elif child.type in class_types:
            name = _get_node_name(child)
            if name:
                boundaries.append(
                    SymbolBoundary(
                        name=name,
                        kind="class",
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                    )
                )

    return boundaries


def find_symbol_source(
    source: str, symbol_name: str, language: str
) -> str | None:
    """查找指定名称的符号（函数/类）的完整源码。

    遍历整个 AST 树，匹配名称后按字节偏移切出源码片段。

    Args:
        source: 完整源码文本。
        symbol_name: 要查找的符号名称。
        language: 语言名称。

    Returns:
        符号的完整源码文本，未找到或语法不可用时返回 None。
    """
    parser = _get_parser(language)
    if parser is None:
        return None

    try:
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return None

    node_types = _LANGUAGE_NODE_TYPES.get(language, {})
    all_symbol_types = node_types.get("functions", ()) + node_types.get("classes", ())

    # 递归遍历整棵树查找匹配的符号。
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in all_symbol_types:
            name = _get_node_name(node)
            if name == symbol_name:
                return _node_source_segment(source, node)
        # 对 TypeScript export 展开一层。
        if language == "typescript" and node.type == "export_statement":
            stack.extend(node.children)
        else:
            stack.extend(node.children)

    return None


def extract_imports(source: str, language: str) -> list[str]:
    """提取源码中的导入模块/包名列表。

    不同语言的提取策略：

    - Python：`import os, sys` → ['os', 'sys']，
              `from pathlib import Path` → ['pathlib']
    - Java：`import java.util.List;` → ['java.util.List']
    - JS/TS：`import { foo } from './bar'` → ['./bar']
    - Go：`import "fmt"` → ['fmt']

    Args:
        source: 完整源码文本。
        language: 语言名称。

    Returns:
        被导入的模块名列表，语法不可用时返回空列表。
    """
    parser = _get_parser(language)
    if parser is None:
        return []

    try:
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        return []

    import_types = _LANGUAGE_NODE_TYPES.get(language, {}).get("imports", ())
    if not import_types:
        return []

    imported: list[str] = []

    if language == "python":
        for node in _walk_collect(tree.root_node, import_types):
            # import_statement: 收集每个 dotted_name 的 name 部分。
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imported.append(child.text.decode("utf-8"))
                    elif child.type == "aliased_import":
                        dotted = child.child_by_field_name("name")
                        if dotted:
                            imported.append(dotted.text.decode("utf-8"))
            # import_from_statement: 收集 module_name 节点文本。
            elif node.type == "import_from_statement":
                module = node.child_by_field_name("module_name")
                if module:
                    imported.append(module.text.decode("utf-8"))

    elif language == "java":
        for node in _walk_collect(tree.root_node, import_types):
            # import_declaration: 取 scoped_identifier 或 identifier 文本。
            for child in node.children:
                if child.type in ("scoped_identifier", "identifier"):
                    text = child.text.decode("utf-8")
                    if text != "static" and text != "*":
                        imported.append(text)

    elif language in ("javascript", "typescript"):
        for node in _walk_collect(tree.root_node, import_types):
            # import_statement: 取 source 子节点（即模块路径）。
            source_node = node.child_by_field_name("source")
            if source_node:
                text = source_node.text.decode("utf-8")
                # 去掉字符串引号。
                text = text.strip("\"'`")
                imported.append(text)

    elif language == "go":
        for node in _walk_collect(tree.root_node, import_types):
            # import_declaration: 遍历 import_spec 子节点。
            for child in node.children:
                if child.type == "import_spec":
                    # import_spec 的 name 或 path 字段。
                    path_node = child.child_by_field_name("path")
                    if path_node:
                        text = path_node.text.decode("utf-8")
                        text = text.strip("\"`")
                        imported.append(text)

    return imported


def _walk_collect(root, target_types: tuple[str, ...]) -> list:
    """遍历树收集所有匹配指定节点类型的节点。"""
    result: list = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in target_types:
            result.append(node)
        stack.extend(node.children)
    return result
