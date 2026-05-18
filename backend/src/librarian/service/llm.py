from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider


def build_llm_model(model_string: str, anthropic_api_key: str) -> AnthropicModel:
    """Build a pydantic-ai LLM model from a "<provider>:<model>" string and
    an explicit API key. Currently only `anthropic` is wired up; add a new
    branch here to support more providers.
    """
    provider_name, model_name = model_string.split(":", 1)
    if provider_name != "anthropic":
        raise ValueError(
            f"Unsupported LLM provider '{provider_name}'. "
            "Only 'anthropic' is wired up; extend build_llm_model to add more."
        )
    return AnthropicModel(
        model_name, provider=AnthropicProvider(api_key=anthropic_api_key)
    )
