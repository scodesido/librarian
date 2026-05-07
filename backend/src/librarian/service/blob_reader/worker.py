from asyncio import sleep


async def run_worker():
    while True:
        print("Running", flush=True)
        await sleep(1)
