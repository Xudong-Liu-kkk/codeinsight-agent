"""大模型 Provider 抽象与客户端封装。

当前阶段先统一 Provider 配置协议，便于后续接入 ask/review 等 Agent 能力。
底层默认复用 OpenAI 兼容接口，因此可以同时兼容多家云模型与本地 Ollama。
"""

from dataclasses import dataclass
import os


# DEFAULT_PROVIDER 为默认 Provider 名称。
DEFAULT_PROVIDER = "ollama"
# DEFAULT_OPENAI_BASE_URL 为 OpenAI 官方兼容接口地址。
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
# DEFAULT_OPENAI_MODEL 为 OpenAI 默认模型名。
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
# DEFAULT_DEEPSEEK_BASE_URL 为 DeepSeek OpenAI 兼容接口地址。
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
# DEFAULT_DEEPSEEK_MODEL 为 DeepSeek 默认模型名。
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
# DEFAULT_QWEN_BASE_URL 为通义千问 OpenAI 兼容接口地址。
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# DEFAULT_QWEN_MODEL 为通义千问默认模型名。
DEFAULT_QWEN_MODEL = "qwen-plus"
# DEFAULT_OLLAMA_BASE_URL 为本地 Ollama OpenAI 兼容接口地址。
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
# DEFAULT_OLLAMA_MODEL 为 Ollama 默认模型名。
DEFAULT_OLLAMA_MODEL = "qwen3:8b"


@dataclass(slots=True)
class ProviderDefaults:
    """单个 Provider 的默认配置。"""

    # provider 为统一 Provider 标识。
    provider: str
    # default_model 为默认模型名。
    default_model: str
    # default_base_url 为默认兼容接口地址。
    default_base_url: str
    # api_key_envs 为 API Key 候选环境变量，按优先级排序。
    api_key_envs: tuple[str, ...]
    # default_api_key 为某些本地 Provider 的占位 Key。
    default_api_key: str | None = None


PROVIDER_DEFAULTS: dict[str, ProviderDefaults] = {
    "openai": ProviderDefaults(
        provider="openai",
        default_model=DEFAULT_OPENAI_MODEL,
        default_base_url=DEFAULT_OPENAI_BASE_URL,
        api_key_envs=("CODEINSIGHT_OPENAI_API_KEY", "OPENAI_API_KEY"),
    ),
    "deepseek": ProviderDefaults(
        provider="deepseek",
        default_model=DEFAULT_DEEPSEEK_MODEL,
        default_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        api_key_envs=("CODEINSIGHT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
    ),
    "qwen": ProviderDefaults(
        provider="qwen",
        default_model=DEFAULT_QWEN_MODEL,
        default_base_url=DEFAULT_QWEN_BASE_URL,
        api_key_envs=("CODEINSIGHT_QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    ),
    "ollama": ProviderDefaults(
        provider="ollama",
        default_model=DEFAULT_OLLAMA_MODEL,
        default_base_url=DEFAULT_OLLAMA_BASE_URL,
        api_key_envs=("CODEINSIGHT_OLLAMA_API_KEY",),
        default_api_key="ollama",
    ),
}


@dataclass(slots=True)
class LLMConfig:
    """统一的大模型配置。"""

    # provider 为当前选中的 Provider。
    provider: str
    # api_key 为兼容接口所需的密钥或占位值。
    api_key: str
    # model 为实际调用的模型名称。
    model: str
    # base_url 为 OpenAI 兼容接口地址。
    base_url: str


class LLMConfigError(RuntimeError):
    """大模型配置错误。"""


def get_supported_providers() -> list[str]:
    """返回当前支持的 Provider 列表。"""

    return sorted(PROVIDER_DEFAULTS)


def _load_api_key(defaults: ProviderDefaults) -> str:
    """按 Provider 规则读取 API Key。"""

    for env_name in defaults.api_key_envs:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value
    if defaults.default_api_key is not None:
        return defaults.default_api_key
    joined_names = " 或 ".join(defaults.api_key_envs)
    raise LLMConfigError(f"未配置 {defaults.provider} 的 API Key，请设置 {joined_names}。")


def load_llm_config(provider: str | None = None) -> LLMConfig:
    """从环境变量读取统一 LLM 配置。"""

    # provider_name 支持统一环境变量覆盖，便于命令行层不显式传参时切换 Provider。
    provider_name = (provider or os.getenv("CODEINSIGHT_LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    defaults = PROVIDER_DEFAULTS.get(provider_name)
    if defaults is None:
        supported = ", ".join(get_supported_providers())
        raise LLMConfigError(f"不支持的 LLM Provider：{provider_name}。当前支持：{supported}。")
    # 每个 Provider 都允许统一变量和专属变量共同覆盖 model/base_url。
    provider_upper = provider_name.upper()
    model = (
        os.getenv("CODEINSIGHT_LLM_MODEL")
        or os.getenv(f"CODEINSIGHT_{provider_upper}_MODEL")
        or defaults.default_model
    )
    base_url = (
        os.getenv("CODEINSIGHT_LLM_BASE_URL")
        or os.getenv(f"CODEINSIGHT_{provider_upper}_BASE_URL")
        or defaults.default_base_url
    )
    api_key = _load_api_key(defaults)
    return LLMConfig(provider=provider_name, api_key=api_key, model=model, base_url=base_url)


def load_env_from_dir(root: str) -> None:
    """从指定目录加载 .env 文件中的环境变量。

    已存在的系统环境变量不会被 .env 覆盖（override=False）。
    """
    from pathlib import Path

    from dotenv import load_dotenv

    env_path = Path(root) / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _get_langfuse_callback():
    """如果配置了 LangFuse 环境变量，返回 CallbackHandler。

    需要设置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY，
    LangFuse v4 自动从环境变量读取 host / base_url 等配置。
    """
    import os as _os

    public_key = _os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = _os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        return None

    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def create_langchain_chat_model(provider: str | None = None):
    """根据配置创建 LangChain ChatOpenAI 实例。

    允许 Agent 层通过 LangChain 框架使用统一的 Provider 配置，
    包括自定义 base_url 和 api_key，兼容 openai / deepseek / qwen / ollama。

    针对 DeepSeek V4 系列模型自动关闭 thinking 模式，
    避免 reasoning_content 在 Agent 多轮对话中被丢弃导致 API 400 错误。

    如果配置了 LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY 环境变量，
    自动注入 LangFuse CallbackHandler，全链路追踪 LLM 调用。
    """
    from langchain_openai import ChatOpenAI

    config = load_llm_config(provider=provider)
    extra_body: dict | None = None
    if config.provider == "deepseek" and "v4" in config.model.lower():
        extra_body = {"thinking": {"type": "disabled"}}

    callbacks = []
    lf_handler = _get_langfuse_callback()
    if lf_handler:
        callbacks.append(lf_handler)

    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=0.2,
        callbacks=callbacks if callbacks else None,
        **({"extra_body": extra_body} if extra_body else {}),
    )
