"""`python -m app kb-demo` — загрузка демо-базы знаний (PLAN Фаза 1, задача 6).

Идемпотентно: существующие продукты обновляются, уже загруженные документы
(по заголовку) не дублируются.
"""

import asyncio
from pathlib import Path
from typing import Any

import yaml

from app.container import get_container
from app.repositories import kb as repo
from app.services.kb.ingest import NewKbFile
from app.tasks.ingest import build_ingest_service

DEFAULT_DIR = Path("evals/fixtures/kb")


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


async def run(directory: Path = DEFAULT_DIR) -> int:
    container = get_container()
    products = await asyncio.to_thread(_load_yaml, directory / "products.yaml")
    documents = await asyncio.to_thread(_load_yaml, directory / "documents.yaml")
    async with container.session_factory() as session, session.begin():
        for product in products:
            await repo.upsert_product(
                session, product["key"], product["name"], product.get("description")
            )
    service = build_ingest_service()
    for item in documents:
        async with container.session_factory() as session:
            existing = await repo.find_document_by_title(session, item["title"])
        if existing is not None:
            print(f"• {item['title']}: уже загружен (#{existing.id})")  # noqa: T201 — CLI-вывод
            continue
        content = await asyncio.to_thread((directory / item["file"]).read_bytes)
        document_id = await service.register_file(
            NewKbFile(
                title=item["title"],
                filename=item["file"],
                content=content,
                language=item["language"],
                product_key=item.get("product"),
            )
        )
        chunks = await service.ingest(document_id)
        print(f"✔ {item['title']}: #{document_id}, чанков {chunks}")  # noqa: T201
    await container.engine.dispose()
    return 0
