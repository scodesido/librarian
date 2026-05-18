from logging import INFO, WARNING, Formatter, StreamHandler, getLogger
from sys import stdout


def configure_logging() -> None:
    """Root logger at WARNING, `librarian.*` at INFO.

    Anything under our package (every module ends up as `librarian....`)
    inherits the INFO level via logger hierarchy. Third-party libraries
    (asyncio, aiohttp, pydantic-ai, etc.) inherit from the root and stay
    at WARNING, which keeps the stream readable during long-running worker
    iterations.
    """
    handler = StreamHandler(stdout)
    handler.setFormatter(Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = getLogger()
    root.setLevel(WARNING)
    root.handlers.clear()
    root.addHandler(handler)
    getLogger("librarian").setLevel(INFO)
