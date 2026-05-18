import logging
from argparse import ArgumentParser
from asyncio import CancelledError, gather
from asyncio import run as asyncio_run

from watchfiles import run_process as watch_process

from librarian.service.blob_extractor.worker import (
    run_worker as run_blob_extractor_worker,
)
from librarian.service.logging import configure_logging
from librarian.service.node_extractor.worker import (
    run_worker as run_node_extractor_worker,
)
from librarian.service.settings import settings
from librarian.service.tree_builder.worker import (
    run_worker as run_tree_builder_worker,
)

logger = logging.getLogger(__name__)


async def run_workers_async() -> None:
    arg_parser = ArgumentParser()
    arg_parser.add_argument("--service", action="append")
    args = arg_parser.parse_args()

    service_selection: list[str] | None = args.service
    service_workers = {
        "blob-extractor": run_blob_extractor_worker,
        "tree-builder": run_tree_builder_worker,
        "node-extractor": run_node_extractor_worker,
    }
    if service_selection is not None and len(service_selection) > 0:
        service_workers = {
            k: v for k, v in service_workers.items() if k in service_selection
        }
    logger.info("service: starting workers %s", sorted(service_workers))
    try:
        await gather(*[worker() for worker in service_workers.values()])
    except CancelledError:
        pass


def run_workers() -> None:
    configure_logging()
    asyncio_run(run_workers_async())


def reload_callback(changes: object) -> None:
    print("Reloading", flush=True)


def entrypoint() -> None:
    if settings.service.autoreload:
        watch_process(".", target=run_workers, callback=reload_callback)
    else:
        run_workers()
