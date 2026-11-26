"""Rotating SQLite snapshots before startup migrations."""
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


async def save_backup(db_path):
    path = Path(db_path)
    if not path.is_file() or not path.stat().st_size:
        return
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{path.name}.{stamp}.sqlite"
    staging = target.with_suffix(".tmp")
    try:
        async with aiosqlite.connect(path) as source, aiosqlite.connect(staging) as destination:
            await source.backup(destination)
            async with destination.execute("PRAGMA quick_check") as cur:
                if (await cur.fetchone())[0] != "ok":
                    raise RuntimeError("Резервная копия SQLite не прошла проверку")
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)
    backups = sorted((p for p in folder.iterdir() if p.is_file() and p.name.startswith(path.name + ".")
                      and p.suffix == ".sqlite"), reverse=True)
    for old in backups[5:]:
        old.unlink()
