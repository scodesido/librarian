from pydantic import BaseModel


class OllamaSettings(BaseModel):
    """Local ollama daemon, operator-side infra. Same instance serves every
    user — ollama needs no auth, so there's no per-user knob to plumb
    through. Both processes (api, service) read this from the same shared
    YAML; user-picked ollama models in the model catalog all target this
    one daemon.
    """

    # Daemon URL. The container reaches the host via host.docker.internal
    # (see docker-compose.yaml extra_hosts); a non-containerised dev run
    # leaves the default localhost.
    host: str = "http://localhost:11434"

    # Context window (in tokens) requested from ollama per call. Ollama's
    # default is 4096, which silently truncates anything longer — bad
    # when our prompt carries a multi-page image blob (~256 tokens/page)
    # plus the running summary and instructions. 16384 fits a typical
    # 5-page blob with headroom; bump higher if you have GPU memory and
    # use a model with a larger native context (qwen2.5: 32k, gemma3:
    # 128k). Passed through pydantic-ai's OpenAI extra_body to ollama's
    # OpenAI-compat handler, which reads it from `options.num_ctx`.
    num_ctx: int = 16384
