"""文件读取引擎测试。"""

from codeinsight.engine import run_read


def test_run_read_returns_evidence_for_valid_file(tmp_path):
    """验证：read 命令可以把安全文件片段转换为证据。"""

    # sample_file 是用于测试读取的项目内文件。
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("a\nb\nc\n", encoding="utf-8")
    # report 是读取命令的结构化报告。
    report = run_read(str(tmp_path), "sample.py", start_line=2, end_line=3)
    assert report.summary
    assert report.findings[0].title == "文件读取成功"
    assert report.evidence[0].snippet == "b\nc"
    assert report.evidence[0].start_line == 2
    assert report.evidence[0].end_line == 3


def test_run_read_reports_error_for_empty_path(tmp_path):
    """验证：空文件路径会返回结构化错误。"""

    # report 是空路径场景下的错误报告。
    report = run_read(str(tmp_path), "   ")
    assert report.findings
    assert report.findings[0].title == "文件路径为空"


def test_run_read_reports_error_for_sensitive_file(tmp_path):
    """验证：敏感文件会被路径安全策略拦截。"""

    # sensitive_file 模拟常见敏感配置文件。
    sensitive_file = tmp_path / ".env"
    sensitive_file.write_text("SECRET=1", encoding="utf-8")
    # report 应返回读取失败，而不是泄露文件内容。
    report = run_read(str(tmp_path), ".env")
    assert report.findings[0].title == "文件读取失败"
    assert not report.evidence
