"""符号提取工具测试。"""

import pytest

from codeinsight.tools.symbol_tool import find_symbol_source


def test_find_function_returns_source(tmp_path):
    """验证：可提取指定函数的完整源码。"""
    src = tmp_path / "demo.py"
    src.write_text(
        "def hello(name):\n"
        "    '''打招呼。'''\n"
        "    return f'Hello {name}'\n"
        "\n"
        "def bye(name):\n"
        "    return f'Bye {name}'\n",
        encoding="utf-8",
    )
    result = find_symbol_source(src, "hello")
    assert result is not None
    assert "def hello(name):" in result
    assert "打招呼" in result
    assert "def bye" not in result


def test_find_class_returns_source(tmp_path):
    """验证：可提取类的完整源码。"""
    src = tmp_path / "demo.py"
    src.write_text(
        "class Foo:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "\n"
        "    def bar(self):\n"
        "        return self.x\n",
        encoding="utf-8",
    )
    result = find_symbol_source(src, "Foo")
    assert result is not None
    assert "class Foo:" in result
    assert "def __init__" in result
    assert "def bar" in result


def test_find_nonexistent_returns_none(tmp_path):
    """验证：符号不存在时返回 None。"""
    src = tmp_path / "demo.py"
    src.write_text("x = 1\n", encoding="utf-8")
    assert find_symbol_source(src, "no_such_func") is None


def test_find_unreadable_file_returns_none(tmp_path):
    """验证：不可读文件返回 None。"""
    assert find_symbol_source(tmp_path / "no_such_file.py", "foo") is None


def test_review_cli_supports_symbol():
    """验证：CLI review 命令支持 --symbol 参数。"""
    from codeinsight.cli import _build_parser
    parser = _build_parser()
    args = parser.parse_args([
        "review", "--root", ".", "--path", "agent.py", "--symbol", "run_ask",
    ])
    assert args.symbol == "run_ask"
