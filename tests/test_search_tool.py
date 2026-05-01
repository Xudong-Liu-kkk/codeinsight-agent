"""代码搜索工具测试。"""

from codeinsight.tools.search_tool import search_code


def test_search_code_returns_hits(tmp_path):
    """验证：关键词命中时能够返回结果。"""

    # py_file 是构造命中场景的 Python 文件。
    py_file = tmp_path / "app.py"
    py_file.write_text("def hello():\n    return 'hello'\n", encoding="utf-8")
    # hits 为搜索结果列表。
    hits = search_code(tmp_path, "hello")
    assert hits
    assert "app.py" in hits[0].file_path


def test_search_code_respects_glob_pattern(tmp_path):
    """验证：glob 过滤可以限制文件范围。"""

    # py_file 和 txt_file 用于验证 glob 过滤行为。
    py_file = tmp_path / "a.py"
    txt_file = tmp_path / "a.txt"
    py_file.write_text("token = 1\n", encoding="utf-8")
    txt_file.write_text("token = 2\n", encoding="utf-8")
    # hits 仅应来自 .py 文件。
    hits = search_code(tmp_path, "token", glob_pattern="*.py")
    assert hits
    assert all(hit.file_path.endswith(".py") for hit in hits)


def test_search_code_returns_empty_for_blank_query(tmp_path):
    """验证：空白关键词不会触发搜索。"""

    # hits 为空表示已正确拦截无效查询。
    hits = search_code(tmp_path, "   ")
    assert hits == []

