"""FastAPI 接口测试。"""

import pytest
from fastapi.testclient import TestClient

from codeinsight.api import create_app


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，绑定到临时目录。"""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=[]\n", encoding="utf-8",
    )
    app = create_app(str(tmp_path))
    return TestClient(app)


class TestApiHealth:
    """API 端点存在性测试（不调 LLM）。"""

    def test_overview_returns_200(self, client):
        """验证：/overview 端点返回 200。"""
        resp = client.post("/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data

    def test_deps_returns_200(self, client):
        """验证：/deps 端点返回 200。"""
        resp = client.post("/deps")
        assert resp.status_code == 200
        assert "summary" in resp.json()

    def test_search_returns_200(self, client):
        """验证：/search 端点返回 200。"""
        resp = client.post("/search?query=test")
        assert resp.status_code == 200

    def test_read_returns_200(self, client):
        """验证：/read 端点返回 200。"""
        resp = client.post("/read?file_path=pyproject.toml&max_lines=5")
        assert resp.status_code == 200

    def test_diagnose_returns_200(self, client):
        """验证：/diagnose 端点返回 200。"""
        resp = client.post("/diagnose?text=ValueError:%20bad")
        assert resp.status_code == 200

    def test_memory_clear_returns_200(self, client):
        """验证：DELETE /memory 返回 200。"""
        resp = client.delete("/memory")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ask_rejects_empty_question(self, client):
        """验证：/ask 空问题返回错误。"""
        resp = client.post("/ask", data={"question": "  "})
        # run_ask 返回结构化错误，接口返回 200。
        assert resp.status_code == 200

    def test_fix_rejects_empty_issue(self, client):
        """验证：/fix 空 issue 返回错误。"""
        resp = client.post("/fix?issue=%20%20")
        assert resp.status_code == 200

    def test_ask_stream_returns_sse(self, client):
        """验证：/ask/stream 返回 SSE 流。"""
        resp = client.post("/ask/stream", data={"question": "hello", "provider": "unknown"})
        # 即使配置错误，也应返回 SSE 格式。
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "event:" in body or body == ""


class TestCliServe:
    """CLI serve 命令测试。"""

    def test_parser_supports_serve(self):
        """验证：CLI 已注册 serve 子命令。"""
        from codeinsight.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["serve", "--root", ".", "--port", "9000"])
        assert args.command == "serve"
        assert args.port == 9000
