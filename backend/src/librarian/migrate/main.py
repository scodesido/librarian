import sys
from os import execvpe, getenv

from librarian.migrate.settings import settings


def entrypoint():
    args = [settings.dbmate_path, *sys.argv[1:]]
    env = {
        "PATH": getenv("PATH", ""),
        "DATABASE_URL": settings.database.url,
    }
    execvpe(settings.dbmate_path, args, env)
