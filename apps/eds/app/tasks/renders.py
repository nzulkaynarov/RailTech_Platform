"""Фоновый рендер PDF писем на бланке (P4, B-094): одна задача на хеш, параллельность 1 на весь ансамбль.

- `render_pdf` — очередь `renders`, `lock` = `rt-docs-render`: задачи с одним `lock` Procrastinate выполняет строго
по одной,
  сколько бы воркеров ни было; `queueing_lock` = хеш — один и тот же PDF в очереди один раз. Рендер — в отдельном
  процессе с
  тайм-аутом (`services/render_process.py`), память ограничивает `mem_limit` контейнера воркера.
- `render_sweep` — раз в минуту ставит заново `pending`, постановку которых потеряли (сбой между коммитом и `defer`).
"""

from procrastinate.exceptions import AlreadyEnqueued

from app import clock
from app.container import get_container
from app.services import letter_mail, renders
from app.tasks.queue import queue

LOCK = "rt-docs-render"


@queue.task(name="render_pdf", queue="renders", lock=LOCK, retry=False)
async def render_pdf(render_hash: str) -> str | None:
    container = get_container()
    return await renders.run(
        container.session_factory,
        container.storage,
        container.renderer,
        render_hash,
        on_finished=letter_mail.on_render_finished(container.bus, container.storage),
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
