import asyncio


class ExponentialBackoff:
    """Per-worker error backoff.

    Workers call `wait_and_advance()` after a failed iteration: the current
    delay elapses, then the next delay doubles (capped at `max_seconds`).
    Calling `reset()` after a successful iteration returns the delay to
    `initial_seconds`.

    The class is deliberately stateful per worker instance, not shared: each
    worker tracks its own consecutive-failure streak.
    """

    def __init__(
        self,
        initial_seconds: float,
        max_seconds: float,
        multiplier: float,
    ) -> None:
        self.initial_seconds = initial_seconds
        self.max_seconds = max_seconds
        self.multiplier = multiplier
        self.current_seconds = initial_seconds

    def reset(self) -> None:
        self.current_seconds = self.initial_seconds

    async def wait_and_advance(self) -> None:
        delay = self.current_seconds
        self.current_seconds = min(self.max_seconds, delay * self.multiplier)
        await asyncio.sleep(delay)
