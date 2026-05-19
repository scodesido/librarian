from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings


def build_llm_model(
    model_string: str,
    anthropic_api_key: str | None = None,
    ollama_host: str | None = None,
    ollama_num_ctx: int | None = None,
    cache_instructions: bool = False,
) -> tuple[Model, ModelSettings | None]:
    """Build a pydantic-ai LLM Model from a "<provider>:<model>" string,
    along with any provider-specific request-time `ModelSettings` the
    caller should attach to the Agent (or pass to `agent.run`).

    Supported providers:
      * `anthropic`: requires `anthropic_api_key`. When
        `cache_instructions=True` the returned settings turn on
        `anthropic_cache_instructions`, so the Agent's static
        instructions are cached server-side (5min TTL by default) and
        subsequent requests with the same instructions get a cache hit
        on that prefix.
      * `ollama`: requires `ollama_host`. Uses ollama's OpenAI-compatible
        `/v1/` endpoint via pydantic-ai's `OpenAIChatModel`. When
        `ollama_num_ctx` is given, returns settings that pass
        `extra_body={"options": {"num_ctx": ...}}` so ollama's
        OpenAI-compat handler bumps the context window past its 4096
        default — without this, longer prompts silently truncate.
        `cache_instructions` is ignored — ollama has no equivalent.

    Adding a new provider is a new branch here.
    """
    provider_name, model_name = model_string.split(":", 1)
    if provider_name == "anthropic":
        if anthropic_api_key is None:
            raise ValueError("anthropic provider requires anthropic_api_key to be set")
        anthropic_model = AnthropicModel(
            model_name, provider=AnthropicProvider(api_key=anthropic_api_key)
        )
        anthropic_settings: ModelSettings | None = None
        if cache_instructions:
            anthropic_settings = AnthropicModelSettings(
                anthropic_cache_instructions=True
            )
        return anthropic_model, anthropic_settings
    if provider_name == "ollama":
        if ollama_host is None:
            raise ValueError("ollama provider requires ollama_host to be set")
        ollama_model = OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(
                base_url=f"{ollama_host.rstrip('/')}/v1",
                api_key="ollama",
            ),
        )
        ollama_settings: ModelSettings | None = None
        if ollama_num_ctx is not None:
            ollama_settings = OpenAIChatModelSettings(
                extra_body={"options": {"num_ctx": ollama_num_ctx}}
            )
        return ollama_model, ollama_settings
    raise ValueError(
        f"Unsupported LLM provider '{provider_name}'. "
        "Wire it up by adding a branch in build_llm_model."
    )
