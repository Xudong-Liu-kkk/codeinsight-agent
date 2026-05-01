"""错误诊断工具测试。"""

import pytest

from codeinsight.tools.diagnose_tool import load_traceback_source, parse_python_traceback


def test_parse_python_traceback_extracts_frames_and_exception():
    """验证：标准 Python traceback 可以解析出栈帧和异常摘要。"""

    # traceback_text 模拟 pytest 或 Python 运行时输出的标准 traceback。
    traceback_text = '''Traceback (most recent call last):
  File "app.py", line 10, in <module>
    main()
  File "service.py", line 5, in main
    raise ValueError("bad")
ValueError: bad
'''
    # info 是解析后的结构化 traceback 信息。
    info = parse_python_traceback(traceback_text)
    assert len(info.frames) == 2
    assert info.frames[-1].file_path == "service.py"
    assert info.frames[-1].line_number == 5
    assert info.exception_type == "ValueError"
    assert info.exception_message == "bad"


def test_parse_python_traceback_handles_plain_error_text():
    """验证：普通错误文本不会导致解析失败。"""

    # info 应能兼容没有栈帧的异常摘要。
    info = parse_python_traceback("RuntimeError: failed")
    assert info.frames == []
    assert info.exception_type == "RuntimeError"
    assert info.exception_message == "failed"


def test_load_traceback_source_requires_exactly_one_input(tmp_path):
    """验证：诊断输入必须且只能提供一种来源。"""

    # traceback_file 是用于模拟文件输入的临时文本。
    traceback_file = tmp_path / "traceback.txt"
    traceback_file.write_text("ValueError: bad", encoding="utf-8")
    with pytest.raises(ValueError):
        load_traceback_source()
    with pytest.raises(ValueError):
        load_traceback_source(text="ValueError: bad", traceback_file=str(traceback_file))
