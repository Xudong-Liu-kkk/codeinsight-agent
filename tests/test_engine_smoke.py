"""第一批引擎协议的冒烟测试。

测试重点是验证命令处理函数是否稳定返回统一报告结构，
从而为后续功能扩展提供安全基础。
"""

from codeinsight.engine import run_overview, run_search


def test_run_overview_with_existing_root_returns_summary(tmp_path):
    """验证：当根目录存在时，overview 至少返回非空摘要。"""

    # report 是概览命令的结构化返回对象。
    report = run_overview(str(tmp_path))
    # 断言摘要存在，确保用户侧至少能看到核心结论。
    assert report.summary
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

