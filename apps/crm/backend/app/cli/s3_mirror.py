"""`python -m app s3-mirror` — копия бакетов RustFS в каталог и обратно (бэкап, ADR-0013).

`--dest DIR` выгружает бакеты приложения в `DIR/<bucket>/<key>`;
`--restore DIR` загружает такую копию обратно (существующие объекты перезаписываются).
"""

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.integrations.s3 import ObjectStorage


def local_path(root: Path, bucket: str, key: str) -> Path:
    """Путь файла для ключа; ключи с `..`/абсолютные отвергаются (выход за каталог)."""
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"unsafe object key: {key!r}")
    return root / bucket / Path(*parts)


def buckets() -> list[str]:
    s = get_settings()
    return [s.s3_bucket_kb, s.s3_bucket_documents, s.s3_bucket_attachments]


async def export(storage: ObjectStorage, root: Path, names: list[str]) -> int:
    count = 0
    for bucket in names:
        for key in await storage.list_keys(bucket):
            path = local_path(root, bucket, key)
            data = await storage.get(bucket, key)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
            count += 1
    return count


async def restore(storage: ObjectStorage, root: Path, names: list[str]) -> int:
    count = 0
    for bucket in names:
        base = root / bucket
        files = [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else []
        for path in files:
            key = path.relative_to(base).as_posix()
            data = await asyncio.to_thread(path.read_bytes)
            await storage.put(bucket, key, data, "application/octet-stream")
            count += 1
    return count


async def run(args: argparse.Namespace) -> int:
    storage = ObjectStorage(get_settings())
    if args.restore:
        count = await restore(storage, Path(args.restore), buckets())
        print(f"restored {count} objects from {args.restore}")  # noqa: T201 — CLI-вывод
    else:
        count = await export(storage, Path(args.dest), buckets())
        print(f"exported {count} objects to {args.dest}")  # noqa: T201
    return 0
