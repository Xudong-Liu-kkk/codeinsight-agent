"""review Agent 编排层测试。"""

from codeinsight.agent import run_review
from codeinsight.cli import _build_parser


class FakeChatClient:
    """用于测试 review 流程的假聊天客户端。"""

    def __init__(self, answer: str):
        self.answer = answer
        self.messages: list[dict[str, str]] | None = None

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        self.messages = messages
        return self.answer


def test_run_review_returns_model_answer(tmp_path):
    """验证：review 会读取文件并返回模型审查结果。"""

    target_file = tmp_path / "demo.py"
    target_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    fake_client = FakeChatClient("总体评价：代码简单清晰。")
    report = run_review(str(tmp_path), "demo.py", client=fake_client)
    assert report.summary == "总体评价：代码简单清晰。"
    assert report.findings[0].title == "review 已完成只读代码审查"
    assert report.evidence
    assert fake_client.messages is not None
    assert "def add" in fake_client.messages[1]["content"]


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
