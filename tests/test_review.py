"""review Agent 编排层测试。"""

from codeinsight.agent import run_review
from codeinsight.cli import _build_parser


def test_run_review_rejects_empty_path(tmp_path):
    """验证：空文件路径会返回结构化错误。"""
    report = run_review(str(tmp_path), "   ")
    assert report.findings[0].title == "文件路径为空"


def test_run_review_blocks_missing_file(tmp_path):
    """验证：不可读取文件会返回结构化错误。"""
    report = run_review(str(tmp_path), "missing.py")
    assert report.findings[0].title == "待审查文件读取失败"


def test_build_parser_supports_review_command():
    """验证：CLI 已注册 review 子命令。"""
    parser = _build_parser()
    args = parser.parse_args([
        "review",
        "--root",
        ".",
        "--path",
        "src/codeinsight/agent.py",
        "--provider",
        "ollama",
        "--max-lines",
        "120",
    ])
    assert args.command == "review"
    assert args.path == "src/codeinsight/agent.py"
    assert args.provider == "ollama"
    assert args.max_lines == 120
