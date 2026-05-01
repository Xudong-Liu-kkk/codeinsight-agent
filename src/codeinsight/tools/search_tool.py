"""代码搜索工具。"""

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import shutil
import subprocess


# 与目录树工具保持一致的默认忽略目录，避免重复扫描无关目录。
DEFAULT_IGNORED_DIRS: set[str] = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


@dataclass(slots=True)
class SearchHit:
    """单条搜索命中结果。"""

    # file_path 为命中文件路径。
    file_path: str
    # line_number 为命中所在行号（从 1 开始）。
    line_number: int
    # line_text 为命中行文本内容。
    line_text: str


def _search_with_rg(root: Path, query: str, glob_pattern: str | None, max_hits: int) -> list[SearchHit]:
    """优先使用 ripgrep 执行高性能搜索。"""

    # cmd 是 rg 命令参数列表。
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never", query, str(root)]
    if glob_pattern:
        cmd.extend(["--glob", glob_pattern])
    # head_limit 通过 rg 的 max-count 控制结果规模。
    cmd.extend(["--max-count", str(max_hits)])
    # completed 为子进程执行结果对象。
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # rg 返回码 0 表示有命中，1 表示无命中，其他为异常。
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip() or "rg 执行失败。")
    hits: list[SearchHit] = []
    for raw_line in completed.stdout.splitlines():
        # parts 期望格式：path:line:text
        parts = raw_line.split(":", 2)
        if len(parts) != 3:
            continue
        raw_path, raw_line_number, line_text = parts
        try:
            line_number = int(raw_line_number)
        except ValueError:
            continue
        hits.append(SearchHit(file_path=raw_path, line_number=line_number, line_text=line_text))
    return hits[:max_hits]


def _search_with_python(root: Path, query: str, glob_pattern: str | None, max_hits: int) -> list[SearchHit]:
    """当 rg 不可用时，使用 Python 进行回退搜索。"""

    hits: list[SearchHit] = []
    for current_root, dir_names, file_names in root.walk():
        # 过滤忽略目录，减少扫描体积。
        dir_names[:] = [name for name in dir_names if name not in DEFAULT_IGNORED_DIRS]
        current_path = Path(current_root)
        for file_name in file_names:
            # glob_pattern 存在时仅保留匹配文件。
            if glob_pattern and not fnmatch(file_name, glob_pattern):
                continue
            file_path = current_path / file_name
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                # 跳过二进制或不可读文件，保证流程稳定。
                continue
            for index, line_text in enumerate(lines, start=1):
                if query in line_text:
                    hits.append(
                        SearchHit(
                            file_path=str(file_path),
                            line_number=index,
                            line_text=line_text,
                        )
                    )
                    if len(hits) >= max_hits:
                        return hits
    return hits


def search_code(
    root: Path,
    query: str,
    glob_pattern: str | None = None,
    max_hits: int = 50,
) -> list[SearchHit]:
    """在项目目录中搜索关键词，返回命中列表。"""

    # normalized_query 用于去除首尾空白，避免空查询误触发全量扫描。
    normalized_query = query.strip()
    if not normalized_query:
        return []
    # root_resolved 将根目录规范化为绝对路径。
    root_resolved = root.resolve()
    if not root_resolved.exists() or not root_resolved.is_dir():
        raise ValueError(f"搜索根目录无效：{root_resolved}")

    # 优先使用 rg，提高大项目下的搜索性能。
    if shutil.which("rg"):
        return _search_with_rg(root_resolved, normalized_query, glob_pattern, max_hits)
    # 无 rg 时回退到 Python 方案，保证功能可用性。
    return _search_with_python(root_resolved, normalized_query, glob_pattern, max_hits)

