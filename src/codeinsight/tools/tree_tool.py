"""项目目录树工具。"""

from dataclasses import dataclass
from pathlib import Path


# 默认忽略目录集合，避免无关或超大目录影响分析速度。
DEFAULT_IGNORED_DIRS: set[str] = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


@dataclass(slots=True)
class TreeSummary:
    """目录树摘要结果。"""

    # total_dirs 表示已统计到的目录数量。
    total_dirs: int
    # total_files 表示已统计到的文件数量。
    total_files: int
    # sampled_lines 保存可读目录树样例文本。
    sampled_lines: list[str]


def list_project_tree(root: Path, max_depth: int = 3) -> TreeSummary:
    """扫描项目目录并返回统计与样例树文本。"""

    # root_resolved 统一为绝对路径，减少路径歧义。
    root_resolved = root.resolve()
    # total_dirs 用于累计目录数量。
    total_dirs = 0
    # total_files 用于累计文件数量。
    total_files = 0
    # sampled_lines 用于承载终端可直接展示的目录树文本。
    sampled_lines: list[str] = [f"{root_resolved.name}/"]

    def _walk(current: Path, depth: int, prefix: str) -> None:
        """递归遍历目录，收集统计和样例文本。"""

        nonlocal total_dirs, total_files
        # 深度超过限制时停止递归，防止输出过大。
        if depth > max_depth:
            return
        # entries 获取当前目录下排序后的子项。
        entries = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        # visible_entries 过滤掉忽略目录，减少噪声。
        visible_entries = [entry for entry in entries if entry.name not in DEFAULT_IGNORED_DIRS]
        for index, entry in enumerate(visible_entries):
            # is_last 用于决定树状连接符样式。
            is_last = index == len(visible_entries) - 1
            # branch_symbol 是当前节点的树状前缀。
            branch_symbol = "└── " if is_last else "├── "
            sampled_lines.append(f"{prefix}{branch_symbol}{entry.name}")
            if entry.is_dir():
                total_dirs += 1
                # child_prefix 为子级节点生成新的缩进前缀。
                child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
                _walk(entry, depth + 1, child_prefix)
            else:
                total_files += 1

    _walk(root_resolved, depth=1, prefix="")
    return TreeSummary(total_dirs=total_dirs, total_files=total_files, sampled_lines=sampled_lines[:80])

