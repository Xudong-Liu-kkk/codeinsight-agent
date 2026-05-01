"""路径安全校验工具测试。"""

from pathlib import Path

import pytest

from codeinsight.tools.path_guard import guard_readable_path


def test_guard_readable_path_allows_path_inside_root(tmp_path):
    """验证：根目录内普通文件允许通过安全校验。"""

    # target_file 是位于根目录中的普通文件。
    target_file = tmp_path / "normal.txt"
    target_file.write_text("ok", encoding="utf-8")
    # safe_path 为安全校验后返回的可读路径。
    safe_path = guard_readable_path(tmp_path, target_file)
    assert safe_path == target_file.resolve()


def test_guard_readable_path_blocks_path_outside_root(tmp_path):
    """验证：根目录外路径会被拦截。"""

    # outside_file 模拟项目外部文件路径。
    outside_file = Path(__file__).resolve()
    with pytest.raises(ValueError):
        guard_readable_path(tmp_path, outside_file)


def test_guard_readable_path_blocks_sensitive_file(tmp_path):
    """验证：敏感文件名默认禁止读取。"""

    # sensitive_file 模拟常见敏感配置文件。
    sensitive_file = tmp_path / ".env"
    sensitive_file.write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(ValueError):
        guard_readable_path(tmp_path, sensitive_file)

