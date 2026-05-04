"""Agent 工具定义测试。"""

from codeinsight.agent_tools import _report_to_text, create_tools
from codeinsight.schemas import AnalysisReport, CodeEvidence, Finding


def _make_tools(root: str):
    """解包 create_tools 返回的 (tools, get_evidence)。"""
    return create_tools(root)


def test_create_tools_returns_five_tools(tmp_path):
    """验证：create_tools 返回 5 个 LangChain 工具和证据收集器。"""
    tools, get_evidence = create_tools(str(tmp_path))
    assert len(tools) == 5
    tool_names = {t.name for t in tools}
    assert tool_names == {"overview", "search", "read", "diagnose", "deps"}
    assert callable(get_evidence)


def test_overview_tool_collects_evidence(tmp_path):
    """验证：overview 工具执行后证据收集器可返回证据。"""
    (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
    tools, get_evidence = create_tools(str(tmp_path))
    overview_tool = next(t for t in tools if t.name == "overview")
    result = overview_tool.invoke({})
    assert "项目概览" in result or "目录" in result.lower()
    evidence = get_evidence()
    assert len(evidence) >= 1
    assert evidence[0].reason.startswith("[Agent 调用 overview]")


def test_search_tool_collects_evidence(tmp_path):
    """验证：search 工具执行后证据带有调用标记。"""
    (tmp_path / "demo.py").write_text("def run_search():\n    pass\n", encoding="utf-8")
    tools, get_evidence = create_tools(str(tmp_path))
    search_tool = next(t for t in tools if t.name == "search")
    result = search_tool.invoke({"query": "run_search"})
    assert "run_search" in result or "命中" in result
    evidence = get_evidence()
    assert len(evidence) >= 1
    assert "[Agent 调用 search('run_search')]" in evidence[0].reason


def test_read_tool_collects_evidence(tmp_path):
    """验证：read 工具执行后证据带有文件路径。"""
    (tmp_path / "demo.py").write_text("# hello world\nprint(42)\n", encoding="utf-8")
    tools, get_evidence = create_tools(str(tmp_path))
    read_tool = next(t for t in tools if t.name == "read")
    result = read_tool.invoke({"file_path": "demo.py", "start_line": 1, "end_line": 2})
    assert "hello" in result
    evidence = get_evidence()
    assert len(evidence) >= 1
    assert "[Agent 调用 read('demo.py')]" in evidence[0].reason


def test_deps_tool_works_on_missing_pyproject(tmp_path):
    """验证：deps 工具在缺少 pyproject.toml 时返回错误信息。"""
    tools, get_evidence = create_tools(str(tmp_path))
    deps_tool = next(t for t in tools if t.name == "deps")
    result = deps_tool.invoke({})
    assert "不存在" in result or "失败" in result or "未找到" in result


def test_get_evidence_accumulates_across_tools(tmp_path):
    """验证：多次调用不同工具后，证据收集器返回全部证据。"""
    (tmp_path / "demo.py").write_text("def foo():\n    return 42\n", encoding="utf-8")
    tools, get_evidence = create_tools(str(tmp_path))

    overview_tool = next(t for t in tools if t.name == "overview")
    search_tool = next(t for t in tools if t.name == "search")

    overview_tool.invoke({})
    search_tool.invoke({"query": "foo"})

    evidence = get_evidence()
    # 至少 overview + search 各一条。
    assert len(evidence) >= 2
    reasons = [ev.reason for ev in evidence]
    assert any("overview" in r for r in reasons)
    assert any("search" in r for r in reasons)


def test_report_to_text_formats_report():
    """验证：_report_to_text 能正确格式化 AnalysisReport。"""
    report = AnalysisReport(
        summary="测试摘要",
        findings=[
            Finding(title="发现1", severity="info", detail="详情1", suggestion="建议1"),
        ],
        evidence=[
            CodeEvidence(
                file_path="test.py",
                start_line=1,
                end_line=3,
                snippet="def foo():\n    pass\n",
                reason="测试证据",
            ),
        ],
        recommendations=["建议A", "建议B"],
        confidence="high",
    )
    text = _report_to_text(report)
    assert "测试摘要" in text
    assert "发现1" in text
    assert "test.py" in text
    assert "def foo" in text
    assert "建议A" in text
