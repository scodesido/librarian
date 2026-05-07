from aiohttp import ClientSession

DRIVE_FILE_URL = "https://www.googleapis.com/drive/v3/files"


async def download_file(http: ClientSession, access_token: str, file_id: str) -> bytes:
    async with http.get(
        f"{DRIVE_FILE_URL}/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"alt": "media"},
    ) as resp:
        resp.raise_for_status()
        return await resp.read()
