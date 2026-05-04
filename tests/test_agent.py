"""ask Agent 编排层测试。"""

from codeinsight.agent import run_ask


def test_run_ask_rejects_empty_question(tmp_path):
    """验证：空问题会返回结构化错误。"""
    report = run_ask(str(tmp_path), "   ")
    assert report.findings[0].title == "问题为空"


def test_run_ask_handles_missing_root():
    """验证：无效根目录会返回结构化错误。"""
    report = run_ask("d:/not-exist-root-for-codeinsight", "这个项目是做什么的？")
    assert report.findings[0].title == "根目录路径无效"
