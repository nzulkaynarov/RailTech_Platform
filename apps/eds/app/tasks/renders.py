"""Фоновый рендер PDF писем на бланке (P4, B-094): одна задача на хеш, параллельность 1 на весь ансамбль.

- `render_pdf` — очередь `renders`, `lock` = `rt-docs-render`: задачи с одним `lock` Procrastinate выполняет строго
по одной,
  сколько бы воркеров ни было; `queueing_lock` = хеш — один и тот же PDF в очереди один раз. Рендер — в отдельном
  процессе с
  тайм-аутом (`services/render_process.py`), память ограничивает `mem_limit` контейнера воркера.
- `render_sweep` — раз в минуту ставит заново `pending`, постановку которых потеряли (сбой между коммитом и `defer`).
"""

from collections.abc import Awaitable, Callable

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.container import Container, get_container
from app.models import DocumentRender
from app.services import call_note, letter_mail, renders
from app.tasks.queue import queue

LOCK = "rt-docs-render"


def on_render_finished(container: Container) -> Callable[[AsyncSession, DocumentRender], Awaitable[None]]:
    """Все хуки итога рендера worker'а: письмо на бланке и записка о звонке."""
    mail = letter_mail.on_render_finished(container.bus, container.storage)
    note = call_note.on_render_finished(container.storage)

    async def finished(session: AsyncSession, row: DocumentRender) -> None:
        await mail(session, row)
        await note(session, row)

    return finished


@queue.task(name="render_pdf", queue="renders", lock=LOCK, retry=False)
async def render_pdf(render_hash: str) -> str | None:
    container = get_container()
    return await renders.run(
        container.session_factory,
        container.storage,
        container.renderer,
        render_hash,
        on_finished=on_render_finished(container),
    )


async def defer(render_hashes: list[str]) -> None:
    for render_hash in render_hashes:
        try:
            await render_pdf.configure(queueing_lock=render_hash).defer_async(render_hash=render_hash)
        except AlreadyEnqueued:
            continue


@queue.periodic(cron="* * * * *", periodic_id="render_sweep")
@queue.task(name="render_sweep", queue="maintenance", queueing_lock="render_sweep")
async def render_sweep(timestamp: int) -> int:
    """Раз в минуту: `pending` старше минуты — снова в очередь (задача на хеш одна)."""
    async with get_container().session_factory() as session:
        stale = await renders.stale_pending(session, clock.now())
    await defer(stale)
    return len(stale)
