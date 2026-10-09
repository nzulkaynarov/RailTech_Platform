"""`python -m app kb-ingest` — загрузка файлов в базу знаний (PLAN Фаза 1, задача 5)."""

import argparse
import asyncio
from pathlib import Path

from app.container import get_container
from app.services.kb.ingest import NewKbFile
from app.tasks.ingest import build_ingest_service, enqueue_ingest
from app.tasks.queue import queue


async def run(args: argparse.Namespace) -> int:
    service = build_ingest_service()
    failures = 0
    for raw in args.files:
        path = Path(raw)
        content = await asyncio.to_thread(_read, path)
        if content is None:
            print(f"✖ {path}: файл не найден")  # noqa: T201 — CLI-вывод
            failures += 1
            continue
        document_id = await service.register_file(
            NewKbFile(
                title=args.title or path.stem,
                filename=path.name,
                content=content,
                language=args.language,
                product_key=args.product,
            )
        )
        if args.sync:
            chunks = await service.ingest(document_id)
            print(f"✔ {path.name}: документ #{document_id}, чанков {chunks}")  # noqa: T201
        else:
            async with queue.open_async():
                await enqueue_ingest(document_id)
            print(f"✔ {path.name}: документ #{document_id} поставлен в очередь ингеста")  # noqa: T201
    await get_container().engine.dispose()
    return 1 if failures else 0


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None
