"""文件读取工具测试。"""

import pytest

from codeinsight.tools.read_tool import read_file_lines


def test_read_file_lines_reads_expected_range(tmp_path):
    """验证：按行区间读取可以得到期望内容。"""

    # target_file 是用于测试读取范围的临时文件。
    target_file = tmp_path / "demo.txt"
    target_file.write_text("a\nb\nc\nd\n", encoding="utf-8")
    # result 保存读取工具的结构化返回结果。
    result = read_file_lines(tmp_path, "demo.txt", start_line=2, end_line=3)
    assert result.content == "b\nc"
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.truncated is False


def test_read_file_lines_marks_truncated_when_exceed_max(tmp_path):
    """验证：超过最大行数时会发生截断并打标。"""

    # target_file 是用于构造超长读取场景的临时文件。
    target_file = tmp_path / "long.txt"
    target_file.write_text("1\n2\n3\n4\n", encoding="utf-8")
    # result 应在 max_lines=2 时仅返回前两行。
    result = read_file_lines(tmp_path, "long.txt", start_line=1, end_line=4, max_lines=2)
    assert result.content == "1\n2"
    assert result.end_line == 2
    assert result.truncated is True


def test_read_file_lines_blocks_invalid_path(tmp_path):
    """验证：越界或不存在路径会抛出错误。"""

    with pytest.raises(ValueError):
        read_file_lines(tmp_path, "../outside.txt")

