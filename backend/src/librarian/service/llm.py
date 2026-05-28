from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.grok import GrokProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings


def build_llm_model(
    model_string: str,
    api_token: str | None = None,
    ollama_host: str | None = None,
    ollama_num_ctx: int | None = None,
    cache_instructions: bool = False,
) -> tuple[Model, ModelSettings | None]:
    """Build a pydantic-ai LLM Model from a "<provider>:<model>" string,
    along with any provider-specific request-time `ModelSettings` the
    caller should attach to the Agent (or pass to `agent.run`).

    `api_token` is the generic credential consumed by whichever provider
    branch the model string selects. The caller keeps one token field
    per LLM slot (`llm_api_token`) rather than one per provider, so the
    settings shape doesn't change when the operator (or, later, the end
    user via the UI) switches providers.

    Supported providers:
      * `anthropic`: requires `api_token`. When
        `cache_instructions=True` the returned settings turn on
        `anthropic_cache_instructions`, so the Agent's static
        instructions are cached server-side (5min TTL by default) and
        subsequent requests with the same instructions get a cache hit
        on that prefix.
      * `openai`: requires `api_token`. Uses pydantic-ai's
        `OpenAIChatModel` against the standard OpenAI API.
        `cache_instructions` is a no-op — OpenAI handles prompt caching
        automatically server-side for sufficiently long prompts, no
        client-side marker is required.
      * `xai`: requires `api_token`. Uses pydantic-ai's `GrokProvider`,
        which wraps x.ai's OpenAI-compatible HTTPS endpoint with the
        correct Grok model profile, so `OpenAIChatModel` is the right
        wrapper here too. `cache_instructions` is a no-op.
      * `ollama`: requires `ollama_host`. Uses ollama's OpenAI-compatible
        `/v1/` endpoint via pydantic-ai's `OpenAIChatModel`. When
        `ollama_num_ctx` is given, returns settings that pass
        `extra_body={"options": {"num_ctx": ...}}` so ollama's
        OpenAI-compat handler bumps the context window past its 4096
        default — without this, longer prompts silently truncate.
        `cache_instructions` is ignored — ollama has no equivalent.
        `api_token` is unused (ollama needs no auth).

    Adding a new provider is a new branch here.
    """
    provider_name, model_name = model_string.split(":", 1)
    if provider_name == "anthropic":
        if api_token is None:
            raise ValueError("anthropic provider requires api_token to be set")
        anthropic_model = AnthropicModel(
            model_name, provider=AnthropicProvider(api_key=api_token)
        )
        anthropic_settings: ModelSettings | None = None
        if cache_instructions:
            anthropic_settings = AnthropicModelSettings(
                anthropic_cache_instructions=True
            )
        return anthropic_model, anthropic_settings
    if provider_name == "openai":
        if api_token is None:
            raise ValueError("openai provider requires api_token to be set")
        openai_model = OpenAIChatModel(
            model_name, provider=OpenAIProvider(api_key=api_token)
        )
        return openai_model, None
    if provider_name == "xai":
        if api_token is None:
            raise ValueError("xai provider requires api_token to be set")
        xai_model = OpenAIChatModel(
            model_name, provider=GrokProvider(api_key=api_token)
        )
        return xai_model, None
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
