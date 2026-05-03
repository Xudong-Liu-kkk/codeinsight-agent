"""ask Agent 编排层测试。"""

from codeinsight.agent import run_ask


class FakeChatClient:
    """用于测试 ask 流程的假聊天客户端。"""

    def __init__(self, answer: str):
        self.answer = answer
        self.messages: list[dict[str, str]] | None = None

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        self.messages = messages
        return self.answer


def test_run_ask_returns_model_answer(tmp_path):
    """验证：ask 会把模型回答写入 summary。"""

    # sample_file 用于给 search/read 自动收集提供可命中的上下文。
    sample_file = tmp_path / "demo.py"
    sample_file.write_text("def run_search():\n    return 'ok'\n", encoding="utf-8")
    fake_client = FakeChatClient("这是一个用于代码搜索的示例项目。")
    report = run_ask(str(tmp_path), "run_search 是做什么的？", client=fake_client)
    assert report.summary == "这是一个用于代码搜索的示例项目。"
    assert report.findings
    assert report.evidence
    assert fake_client.messages is not None
    assert "run_search 是做什么的？" in fake_client.messages[1]["content"]


def test_run_ask_rejects_empty_question(tmp_path):
    """验证：空问题会返回结构化错误。"""

    report = run_ask(str(tmp_path), "   ")
    assert report.findings[0].title == "问题为空"


def test_run_ask_handles_missing_root():
    """验证：无效根目录会返回结构化错误。"""

    report = run_ask("d:/not-exist-root-for-codeinsight", "这个项目是做什么的？")
    assert report.findings[0].title == "根目录路径无效"
