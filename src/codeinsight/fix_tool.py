"""自动修复工具模块。

本模块提供文件写入、测试运行和回滚能力，供 fix 命令使用。
这是项目中第一个（也是唯一一个）突破只读边界的模块——
仅限 fix 命令内部使用，不会暴露给 ask / review 等只读 Agent。

修复流程：
  apply_fix → run_tests → 通过 ✅
                      → 失败 → rollback 恢复 .bak
"""

import subprocess
from pathlib import Path


def apply_fix(file_path: str, original: str, replacement: str) -> bool:
    """在文件中执行精确字符串替换，完成一次修复。

    使用精确匹配替换而非行号定位，避免因文件已变更导致的行号漂移。
    如果 original 字符串在文件中出现多次，拒绝执行（防止误改）。

    Args:
        file_path: 要修改的文件路径（绝对或相对路径均可）。
        original: 要替换的原始代码片段，必须与文件内容精确匹配。
        replacement: 替换后的新代码片段。

    Returns:
        True 表示替换成功，False 表示匹配失败（未找到或多处匹配）。
    """
    path = Path(file_path).resolve()
    if not path.exists() or not path.is_file():
        return False

    content = path.read_text(encoding="utf-8")
    count = content.count(original)
    if count == 0:
        return False
    if count > 1:
        # 多处匹配时拒绝执行，防止误改其他位置。
        return False

    new_content = content.replace(original, replacement, 1)

    # Python 文件：编译检查替换后的代码是否有语法错误。
    if path.suffix == ".py":
        try:
            compile(new_content, str(path), "exec")
        except SyntaxError:
            return False

    # 备份原文件为 .bak，便于回滚。
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_text(content, encoding="utf-8")
    path.write_text(new_content, encoding="utf-8")
    return True


def generate_diff(file_path: str, original: str, replacement: str) -> str:
    """生成可读的 unified diff 预览，供用户在确认前审查。

    Args:
        file_path: 文件路径。
        original: 原始代码片段。
        replacement: 替换后的代码片段。

    Returns:
        格式化的 diff 文本。
    """
    import difflib

    original_lines = original.splitlines(keepends=True)
    replacement_lines = replacement.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines,
        replacement_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def rollback(file_path: str) -> bool:
    """从 .bak 备份恢复文件，回滚一次修复。

    Args:
        file_path: 要回滚的文件路径。

    Returns:
        True 表示回滚成功，False 表示备份文件不存在。
    """
    path = Path(file_path).resolve()
    backup_path = path.with_suffix(path.suffix + ".bak")
    if not backup_path.exists():
        return False
    backup_content = backup_path.read_text(encoding="utf-8")
    path.write_text(backup_content, encoding="utf-8")
    # 回滚后删除备份，避免误用过期备份。
    backup_path.unlink()
    return True


def run_tests(root: str) -> tuple[bool, str]:
    """在项目根目录运行 pytest，返回是否通过和输出文本。

    使用 `uv run pytest -q` 运行测试，保证与开发环境一致。
    超时 120 秒，防止测试卡死。

    Args:
        root: 项目根目录路径。

    Returns:
        (passed, output)：passed 为 True 表示测试全部通过，
        output 包含 pytest 的标准输出和错误输出。
    """
    completed = subprocess.run(
        ["uv", "run", "pytest", "-q"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        timeout=120,
    )
    output = completed.stdout.strip() + "\n" + completed.stderr.strip()
    passed = completed.returncode == 0
    return passed, output
