"""第二批引擎协议的冒烟测试。

测试重点是验证工具层接入后，报告结构与关键行为依然稳定。
"""

from codeinsight.engine import run_overview, run_search


def test_run_overview_with_existing_root_returns_summary(tmp_path):
    """验证：overview 在真实目录上返回统计信息。"""

    # report 是概览命令的结构化返回对象。
    report = run_overview(str(tmp_path))
    # 断言摘要存在，确保用户侧至少能看到核心结论。
    assert report.summary
    # 断言 findings 存在，确保目录统计结果已被写入报告。
    assert report.findings
    # 断言置信度值属于预定义集合，避免出现非法状态。
    assert report.confidence in {"high", "medium", "low"}


def test_run_search_with_empty_query_reports_error(tmp_path):
    """验证：当查询为空时，search 返回结构化错误提示。"""

    # 传入空白查询，模拟用户误操作场景。
    report = run_search(str(tmp_path), "   ")
    # 断言 findings 不为空，确保错误信息可被前端或 CLI 展示。
    assert report.findings
    # 断言标题与预期一致，确保错误语义稳定。
    assert report.findings[0].title == "查询内容为空"


def test_run_search_returns_evidence_when_hit(tmp_path):
    """验证：search 命中关键词时会产出证据列表。"""

    # sample_file 是用于构造命中场景的临时代码文件。
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("def run_search():\n    return 'ok'\n", encoding="utf-8")
    # report 是搜索命令的结构化返回对象。
    report = run_search(str(tmp_path), "run_search", "*.py")
    # 命中时应返回至少一条证据，便于定位到具体代码。
    assert report.evidence

