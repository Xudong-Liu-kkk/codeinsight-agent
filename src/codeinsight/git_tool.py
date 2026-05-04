"""Git 操作工具模块。

本模块封装 git diff / log / show 等子进程调用，供 PR 审查功能使用。
选择直接调用 git 命令行而非引入第三方 Git 库（如 GitPython），
原因：
  1. 零额外依赖——git 命令行在开发环境中几乎总是可用；
  2. 输出稳定——git 的 plumbing/porcelain 命令格式是稳定接口；
  3. 安全——子进程调用天然隔离，不会污染项目进程内存。
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess


def _run_git(root: Path, *args: str, timeout: int = 30) -> str:
    """在指定根目录执行 git 命令，返回标准输出文本。

    所有 git 子进程调用统一走此函数，便于集中处理错误、超时和编码。
    git 命令使用 `--no-pager` 风格参数，确保输出不会被分页截断。

    Args:
        root: 项目根目录（git 工作树顶层）。
        *args: 传给 git 的参数，例如 "diff", "--name-only"。
        timeout: 子进程超时秒数，防止意外卡死。

    Returns:
        命令的标准输出文本（尾部空白已保留，由调用方按需 strip）。

    Raises:
        RuntimeError: git 命令返回非零退出码时抛出，错误信息包含 stderr。
    """
    # check=False 表示不自动抛异常，由调用方自行判断。
    completed = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        timeout=timeout,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(stderr or f"git {' '.join(args)} 执行失败。")
    return completed.stdout


# —————————————————————————————— 数据结构 ——————————————————————————————

@dataclass(slots=True)
class DiffResult:
    """一次 git diff 查询的结构化结果。

    Attributes:
        files_changed: 变更文件路径列表（相对于项目根目录），已排序去重。
        diff_content: 完整的 unified diff 文本（context=5 行）。
        summary: 统计摘要，如 "3 files changed, 12 insertions(+), 5 deletions(-)"。
    """

    files_changed: list[str]
    diff_content: str
    summary: str


# —————————————————————————————— diff 获取 ——————————————————————————————

def get_uncommitted_diff(root: Path) -> DiffResult:
    """获取工作区所有未提交的变更（staged + unstaged）。

    合并 `git diff`（unstaged）和 `git diff --cached`（staged）两部分，
    在 diff 文本中用分隔线标注来源，避免混淆。

    典型用法：审查当前工作区的修改，在提交前做自检。
    """
    # 分别获取 unstaged 和 staged 的 diff。
    raw = _run_git(root, "diff", "--unified=5")
    staged = _run_git(root, "diff", "--cached", "--unified=5")

    # 将两部分合并为一份文本，便于一次性交给模型审查。
    combined: list[str] = []
    if staged.strip():
        combined.append("=== 已暂存的变更（staged）===")
        combined.append(staged)
    if raw.strip():
        combined.append("=== 未暂存的变更（unstaged）===")
        combined.append(raw)
    diff_text = "\n".join(combined)

    # 变更文件列表：合并 staged 和 unstaged 的文件名，去重排序。
    files_raw = _run_git(root, "diff", "--name-only")
    files_staged = _run_git(root, "diff", "--cached", "--name-only")
    files = list(set(
        f.strip() for f in (files_raw + files_staged).splitlines() if f.strip()
    ))

    # 生成人可读的统计行，例如 " 2 files changed, 10 insertions(+), 3 deletions(-)"。
    stat = _run_git(root, "diff", "--stat")
    summary = stat.strip().splitlines()[-1] if stat.strip() else "无变更"

    return DiffResult(files_changed=sorted(files), diff_content=diff_text, summary=summary)


def get_branch_diff(root: Path, base: str, head: str) -> DiffResult:
    """获取两个分支之间的差异。

    使用三点语法 `base...head`，只显示 head 分支独有的提交内容，
    而非 base 和 head 的对称差异，更符合 PR 审查的语义。

    Args:
        base: 基准分支名，如 "main"。
        head: 目标分支名，如 "feature/new-api"。
    """
    # 三点语法：git diff main...feature —— 只显示 feature 独有的变更。
    diff_text = _run_git(root, "diff", f"{base}...{head}", "--unified=5")

    # 变更文件列表。
    files_raw = _run_git(root, "diff", "--name-only", f"{base}...{head}")
    files = [f.strip() for f in files_raw.splitlines() if f.strip()]

    # 统计摘要。
    stat = _run_git(root, "diff", "--stat", f"{base}...{head}")
    summary = stat.strip().splitlines()[-1] if stat.strip() else f"{base}...{head}"

    return DiffResult(files_changed=sorted(files), diff_content=diff_text, summary=summary)


def get_commit_diff(root: Path, commit: str) -> DiffResult:
    """获取指定 commit 的变更内容。

    用 `git show` 获取 diff 文本，用 `git diff-tree` 获取文件列表。
    Windows 环境下 diff-tree 偶尔返回空，因此有回退逻辑从 diff 文本中解析。

    Args:
        commit: commit-ish，如 "HEAD"、"abc1234" 或 "HEAD~3"。
    """
    # --format= 抑制 commit message 输出，只保留 diff。
    diff_text = _run_git(root, "show", commit, "--unified=5", "--format=")

    # 优先用 diff-tree 获取精确的文件列表。
    # Windows 上某些 git 版本 diff-tree 输出为空，故增加回退。
    try:
        files_raw = _run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
        files = [f.strip() for f in files_raw.splitlines() if f.strip()]
    except RuntimeError:
        files: list[str] = _parse_files_from_diff(diff_text)
    if not files:
        files = _parse_files_from_diff(diff_text)

    # 统计摘要。
    stat = _run_git(root, "show", commit, "--stat", "--format=")
    summary = stat.strip().splitlines()[-1] if stat.strip() else f"commit {commit[:8]}"

    return DiffResult(files_changed=sorted(files), diff_content=diff_text, summary=summary)


# —————————————————————————————— 辅助函数 ——————————————————————————————

def _parse_files_from_diff(diff_text: str) -> list[str]:
    """从 unified diff 文本中提取变更文件列表。

    用作 `git diff-tree` 失败或返回空时的回退方案。
    依赖 diff 头部的 "diff --git a/<path> b/<path>" 行，这是 git diff
    unified 格式的固定组成部分，跨平台稳定。

    Args:
        diff_text: `git diff` 或 `git show` 的 unified diff 输出。

    Returns:
        去重后的文件路径列表。
    """
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git a/"):
            # 格式：diff --git a/path/to/file.py b/path/to/file.py
            #   [0]     [1]   [2]              [3]
            parts = line.split(" ")
            if len(parts) >= 4:
                # parts[3] 是 "b/path/to/file.py"，去掉 "b/" 前缀。
                file_path = parts[3].replace("b/", "", 1)
                files.append(file_path)
    return files


def get_recent_commits(root: Path, count: int = 3) -> str:
    """获取最近 N 个 commit 的简要信息。

    Args:
        root: 项目根目录。
        count: 返回的 commit 数量，默认 3。

    Returns:
        每行一个 commit，格式为 "<短哈希> <标题>"，按时间倒序。
    """
    return _run_git(root, "log", f"-{count}", "--oneline", "--no-decorate")
