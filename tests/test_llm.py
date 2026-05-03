"""LLM Provider 配置测试。"""

import pytest

from codeinsight.llm import LLMConfigError, get_supported_providers, load_llm_config


def test_get_supported_providers_contains_expected_names():
    """验证：Provider 列表包含当前规划支持的模型来源。"""

    providers = get_supported_providers()
    assert "openai" in providers
    assert "deepseek" in providers
    assert "qwen" in providers
    assert "ollama" in providers


def test_load_llm_config_reads_openai_defaults(monkeypatch):
    """验证：OpenAI Provider 可从统一环境变量读取配置。"""

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    config = load_llm_config("openai")
    assert config.provider == "openai"
    assert config.api_key == "test-openai-key"
    assert config.model == "gpt-4o-mini"
    assert config.base_url == "https://api.openai.com/v1"


def test_load_llm_config_reads_qwen_defaults(monkeypatch):
    """验证：通义千问 Provider 可从 DashScope 变量读取 Key。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-qwen-key")
    config = load_llm_config("qwen")
    assert config.provider == "qwen"
    assert config.api_key == "test-qwen-key"
    assert config.model == "qwen-plus"


def test_load_llm_config_uses_ollama_default_key(monkeypatch):
    """验证：Ollama 在未配置 Key 时使用占位值。"""

    config = load_llm_config("ollama")
    assert config.provider == "ollama"
    assert config.api_key == "ollama"
    assert config.base_url == "http://localhost:11434/v1"


def test_load_llm_config_rejects_unknown_provider():
    """验证：未知 Provider 会返回清晰错误。"""

    with pytest.raises(LLMConfigError):
        load_llm_config("unknown")


def test_load_llm_config_requires_api_key_for_remote_provider(monkeypatch):
    """验证：远程 Provider 未配置 Key 时会报错。"""

    monkeypatch.delenv("CODEINSIGHT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        load_llm_config("openai")
