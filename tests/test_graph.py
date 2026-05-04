"""多步自主分析图测试。"""

from langchain_openai import ChatOpenAI

from codeinsight.agent_tools import create_tools
from codeinsight.graph import MAX_ITERATIONS, AskState, build_ask_graph


def test_build_ask_graph_compiles(tmp_path):
    """验证：图可正常编译。"""
    chat_model = ChatOpenAI(
        model="gpt-4o-mini",
        api_key="test",
        base_url="http://localhost:1/v1",
    )
    tools, _ = create_tools(str(tmp_path))
    graph = build_ask_graph(chat_model, tools)
    assert graph is not None


def test_build_ask_graph_with_memory(tmp_path):
    """验证：带记忆上下文的图可正常编译。"""
    chat_model = ChatOpenAI(
        model="gpt-4o-mini",
        api_key="test",
        base_url="http://localhost:1/v1",
    )
    tools, _ = create_tools(str(tmp_path))
    graph = build_ask_graph(chat_model, tools, "[项目记忆] 已记录 5 个文件。")
    assert graph is not None


def test_ask_state_has_required_keys():
    """验证：AskState 包含所有必需键。"""
    keys = list(AskState.__annotations__)
    assert "messages" in keys
    assert "question" in keys
    assert "plan_steps" in keys
    assert "current_step" in keys
    assert "findings" in keys
    assert "iteration" in keys
    assert "is_sufficient" in keys
    assert "final_answer" in keys


def test_max_iterations_is_reasonable():
    """验证：安全上限在合理范围内。"""
    assert 1 <= MAX_ITERATIONS <= 5
