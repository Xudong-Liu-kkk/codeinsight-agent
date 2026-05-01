"""错误诊断引擎测试。"""

from codeinsight.engine import run_diagnose


def test_run_diagnose_reads_project_frame_evidence(tmp_path):
    """验证：diagnose 能读取项目内 traceback 栈帧附近的源码。"""

    # sample_file 是 traceback 指向的项目内文件。
    sample_file = tmp_path / "app.py"
    sample_file.write_text("def main():\n    raise ValueError('bad')\n", encoding="utf-8")
    traceback_text = f'''Traceback (most recent call last):
  File "{sample_file}", line 2, in main
    raise ValueError('bad')
ValueError: bad
'''
    # report 是错误诊断报告。
    report = run_diagnose(str(tmp_path), text=traceback_text)
    assert report.summary == "已完成错误诊断：ValueError。"
    assert report.evidence
    assert "raise ValueError" in report.evidence[0].snippet


def test_run_diagnose_handles_plain_error_text(tmp_path):
    """验证：diagnose 可以兼容没有标准栈帧的普通错误文本。"""

    # report 是普通错误文本的诊断报告。
    report = run_diagnose(str(tmp_path), text="RuntimeError: failed")
    assert report.summary == "已完成错误诊断：RuntimeError。"
    assert not report.evidence
    assert report.confidence == "medium"
