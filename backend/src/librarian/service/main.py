from argparse import ArgumentParser
from asyncio import CancelledError, gather
from asyncio import run as asyncio_run

from watchfiles import run_process as watch_process

from librarian.service.blob_reader.worker import run_worker as run_blob_reader_worker
from librarian.service.logging import configure_logging
from librarian.service.settings import settings


async def run_workers_async() -> None:
    arg_parser = ArgumentParser()
    arg_parser.add_argument("--service", action="append")
    args = arg_parser.parse_args()

    service_selection: list[str] | None = args.service
    service_workers = {
        "blob-reader": run_blob_reader_worker,
    }
    if service_selection is not None and len(service_selection) > 0:
        service_workers = {
            k: v for k, v in service_workers.items() if k in service_selection
        }
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
