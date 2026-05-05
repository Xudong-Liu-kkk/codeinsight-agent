"""FastAPI REST 接口模块。

将 CodeInsight Agent 的所有能力暴露为 REST API，
支持 ask、review、pr-review、fix、deps、diagnose 等端点。
/ask/stream 端点通过 SSE 流式输出 Agent 的实时分析过程。

启动方式：
  uv run codeinsight serve --root . --port 8888
"""

import asyncio
import json as _json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

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

    # —— 自然语言问答（同步）——
    @app.post("/ask")
    async def ask(question: str, provider: str | None = None):
        """自然语言问答：大模型自主调用工具分析代码库（同步返回）。"""
        report = run_ask(str(root_path), question, provider=provider)
        return _report_to_response(report)

    # —— 自然语言问答（SSE 流式）——
    @app.post("/ask/stream")
    async def ask_stream(question: str, provider: str | None = None):
        """自然语言问答 SSE 流式：实时输出 Agent 的规划和执行过程。

        事件类型：
          plan      — Planner 拆解的任务列表
          step      — Executor 开始执行一个子任务
          token     — Reader Agent 逐 token 输出
          tool_call — 工具调用开始
          tool_result — 工具调用结果
          review    — Reviewer 审查结果
          final     — Synthesizer 生成的最终回答
          done      — 流结束
        """
        from codeinsight.agent_tools import create_tools
        from codeinsight.graph import build_ask_graph
        from codeinsight.llm import LLMConfigError, create_langchain_chat_model
        from codeinsight.memory import ProjectMemory
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        # 初始化。
        try:
            chat_model = create_langchain_chat_model(provider=provider)
        except LLMConfigError as exc:
            error_msg = str(exc)
            async def error_gen():
                yield f"event: error\ndata: {_json.dumps({'error': error_msg})}\n\n"
            return StreamingResponse(error_gen(), media_type="text/event-stream")

        memory = ProjectMemory(root=root_path)
        memory_context = memory.build_context()
        tools, get_evidence = create_tools(str(root_path), memory=memory)
        ask_graph = build_ask_graph(chat_model, tools, memory_context)

        def _sse_format(event: str, data: dict | str) -> str:
            payload = data if isinstance(data, str) else _json.dumps(data, ensure_ascii=False)
            return f"event: {event}\ndata: {payload}\n\n"

        async def event_generator():
            steps_count = 0

            try:
                for chunk in ask_graph.stream(
                    {"messages": [HumanMessage(content=question.strip())]},
                    stream_mode="updates",
                ):
                    for node_name, node_output in chunk.items():
                        if node_name == "planner":
                            steps_count = len(node_output.get("plan_steps", []))
                            yield _sse_format("plan", {
                                "steps": node_output.get("plan_steps", []),
                            })
                        elif node_name == "executor":
                            idx = node_output.get("current_step", 0)
                            yield _sse_format("step", {
                                "current": idx,
                                "total": steps_count,
                            })
                            # Reader Agent 消息通过 state 透传，emit 给前端。
                            for msg in node_output.get("messages", []):
                                content = getattr(msg, "content", None)
                                tc_chunks = getattr(msg, "tool_call_chunks", []) if hasattr(msg, "tool_call_chunks") else []
                                for tc in tc_chunks:
                                    tc_name = getattr(tc, "name", None)
                                    if tc_name:
                                        yield _sse_format("tool_call", {"name": tc_name})
                                if content and isinstance(msg, ToolMessage):
                                    yield _sse_format("tool_result", {
                                        "name": getattr(msg, "name", ""),
                                        "summary": str(content)[:200],
                                    })
                                elif content:
                                    yield _sse_format("token", {"text": str(content)})
                        elif node_name == "reviewer":
                            yield _sse_format("review", {
                                "sufficient": node_output.get("is_sufficient", "NO") == "YES",
                                "iteration": node_output.get("iteration", 0),
                            })
                        elif node_name == "synthesizer":
                            pass

                # 流结束：收集证据和最终回答。
                evidence = get_evidence()
                answer = f"Agent 分析完成，共收集 {len(evidence)} 条证据。详细结果请查看 /ask 同步接口。"

                yield _sse_format("final", {
                    "evidence_count": len(evidence),
                    "summary": answer,
                })

            except Exception as exc:
                yield _sse_format("error", {"error": str(exc)})

            yield _sse_format("done", {})

            # 保存记忆。
            try:
                memory.add_history(question.strip(), answer)
            except Exception:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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
