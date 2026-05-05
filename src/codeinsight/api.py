"""FastAPI REST 接口模块。

将 CodeInsight Agent 的所有能力暴露为 REST API，
支持 ask、review、pr-review、fix、deps、diagnose 等端点。

启动方式：
  uv run codeinsight serve --root . --port 8888
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from codeinsight.agent import run_ask, run_fix, run_pr_review, run_review
from codeinsight.engine import run_deps, run_diagnose, run_overview, run_read, run_search
from codeinsight.memory import ProjectMemory
from codeinsight.schemas import AnalysisReport


def _report_to_response(report: AnalysisReport) -> JSONResponse:
    """将 AnalysisReport 转为 JSON 响应。"""
    return JSONResponse(content=report.to_dict())


def create_app(root: str) -> FastAPI:
    """创建 FastAPI 应用，绑定到指定项目根目录。

    Args:
        root: 项目根目录路径，所有分析操作都在此目录下执行。
    """
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ValueError(f"项目根目录不存在：{root_path}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期：启动时加载 .env，关闭时无需清理。"""
        from codeinsight.llm import load_env_from_dir
        load_env_from_dir(str(root_path))
        yield

    app = FastAPI(
        title="CodeInsight Agent API",
        description="基于 LangGraph 多 Agent 的代码库分析 REST 接口",
        version="0.1.0",
        lifespan=lifespan,
    )

    # —— 自然语言问答 ——
    @app.post("/ask")
    async def ask(question: str, provider: str | None = None):
        """自然语言问答：大模型自主调用工具分析代码库。"""
        report = run_ask(str(root_path), question, provider=provider)
        return _report_to_response(report)

    # —— 代码审查 ——
    @app.post("/review")
    async def review(
        file_path: str,
        symbol: str | None = None,
        provider: str | None = None,
        max_lines: int = 400,
    ):
        """只读代码审查：审查指定文件或其中的符号。"""
        report = run_review(str(root_path), file_path, symbol=symbol, provider=provider, max_lines=max_lines)
        return _report_to_response(report)

    # —— Git PR 审查 ——
    @app.post("/pr-review")
    async def pr_review(
        commit: str | None = None,
        base: str | None = None,
        head: str | None = None,
        provider: str | None = None,
    ):
        """Git PR 审查：审查未提交变更、指定 commit 或分支对比。"""
        report = run_pr_review(str(root_path), base=base, head=head, commit=commit, provider=provider)
        return _report_to_response(report)

    # —— 自动修复 ——
    @app.post("/fix")
    async def fix(issue: str, provider: str | None = None, auto_confirm: bool = False):
        """自动修复：搜索代码、生成修复方案并应用。"""
        report = run_fix(str(root_path), issue, provider=provider, auto_confirm=auto_confirm)
        return _report_to_response(report)

    # —— 项目概览 ——
    @app.post("/overview")
    async def overview():
        """获取项目目录结构概览。"""
        report = run_overview(str(root_path))
        return _report_to_response(report)

    # —— 代码搜索 ——
    @app.post("/search")
    async def search(query: str, glob: str | None = None):
        """搜索代码关键词或符号。"""
        report = run_search(str(root_path), query, glob_pattern=glob)
        return _report_to_response(report)

    # —— 文件读取 ——
    @app.post("/read")
    async def read(
        file_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        max_lines: int = 300,
    ):
        """安全读取项目内文件片段。"""
        report = run_read(str(root_path), file_path, start_line=start_line, end_line=end_line, max_lines=max_lines)
        return _report_to_response(report)

    # —— 错误诊断 ——
    @app.post("/diagnose")
    async def diagnose(text: str):
        """解析 Python traceback 并给出诊断建议。"""
        report = run_diagnose(str(root_path), text=text)
        return _report_to_response(report)

    # —— 依赖分析 ——
    @app.post("/deps")
    async def deps():
        """分析项目依赖配置和风险。"""
        report = run_deps(str(root_path))
        return _report_to_response(report)

    # —— 清空记忆 ——
    @app.delete("/memory")
    async def memory_clear():
        """清空项目长期记忆。"""
        memory = ProjectMemory(root=root_path)
        memory.clear()
        return {"status": "ok", "message": "项目记忆已清空"}

    return app
