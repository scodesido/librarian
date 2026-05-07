from logging import INFO, Formatter, StreamHandler, getLogger
from sys import stdout


def configure_logging() -> None:
    handler = StreamHandler(stdout)
    handler.setFormatter(Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = getLogger()
    root.setLevel(INFO)
    root.handlers.clear()
    root.addHandler(handler)
