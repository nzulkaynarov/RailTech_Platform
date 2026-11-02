"""Рендер PDF письма на бланке в отдельном процессе (B-094, `docs/architecture/rt-docs.md` §7).

Procrastinate выполняет синхронные задачи в потоке (там у `rt_docs` только мягкий тайм-аут), а асинхронная задача с
WeasyPrint блокировала бы цикл событий воркера. Поэтому рендер — в пуле из **одного** процесса (`spawn`): в процессе
пула
функция идёт в главном потоке, и жёсткий тайм-аут `rt_docs` (SIGALRM) работает; поверх — ожидание с запасом и `kill`
процесса с пересозданием пула, если он завис. Параллельность 1 на весь ансамбль держит ещё и `lock` задачи
(`app/tasks/renders.py`).

`render_payload` — функция процесса пула: из `payload` (`services/renders.py`) и байтов логотипа собирает объекты
`rt_docs`
и возвращает PDF и статистику. Импорт `rt_docs.pdf` (pango, harfbuzz) — только здесь и только в процессе пула.
"""

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from typing import Any

RENDER_TIMEOUT_S = 60.0
_GRACE_S = 15.0  # запас сверх тайм-аута rt_docs: проход вёрстки между проверками не прерывается

TIMEOUT = "timeout"
BODY = "body"
LETTERHEAD = "letterhead"
FAILED = "failed"


class RenderError(Exception):
    """Рендер не удался; `code` — `timeout`, `body`, `letterhead` или `failed` (причину словами выбирает вызывающий)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail

    def __reduce__(self) -> tuple[type["RenderError"], tuple[str, str]]:  # исключение идёт из процесса пула pickle'ом
        return (RenderError, (self.code, self.detail))


def render_payload(payload: dict[str, Any], logo: bytes | None, logo_mime: str | None) -> dict[str, Any]:
    """Функция процесса пула: ввод рендера → `{pdf, pages, last_page_fill, warnings}` или `RenderError`."""
    from rt_docs import BodyError, DocumentMeta, Layout, Letterhead, LetterheadError, Logo, RenderTimeoutError
    from rt_docs.pdf import render_pdf

    head = payload["letterhead"]
    meta = payload["meta"]
    try:
        letterhead = Letterhead(
            company_name=head["company_name"],
            requisites=tuple(head["requisites"]),
            footer=tuple(head["footer"]),
            logo=Logo(logo, logo_mime) if logo is not None and logo_mime else None,
            accent=head["accent"],
            font=head["font"],
        )
        result = render_pdf(
            payload["body"],
            letterhead=letterhead,
            layout=Layout(payload["layout"]),
            meta=DocumentMeta(
                title=None,
                number=meta["number"],
                date=date.fromisoformat(meta["date"]) if meta["date"] else None,
                addressee=tuple(meta["addressee"]),
                reply_to=meta["reply_to"],
                executor=meta["executor"],
            ),
            highlight_missing=False,
            timeout_s=RENDER_TIMEOUT_S,
        )
    except RenderTimeoutError as exc:
        raise RenderError(TIMEOUT, str(exc)) from None
    except BodyError as exc:
        raise RenderError(BODY, str(exc)) from None
    except LetterheadError as exc:
        raise RenderError(LETTERHEAD, str(exc)) from None
    return {
        "pdf": result.pdf,
        "pages": result.stats.pages,
        "last_page_fill": result.stats.last_page_fill,
        "warnings": list(result.warnings),
    }


class ProcessRenderer:
    """Пул из одного процесса `spawn` с kill по тайм-ауту; один на процесс воркера (`Container.renderer`)."""

    def __init__(self, timeout_s: float = RENDER_TIMEOUT_S + _GRACE_S) -> None:
        self._timeout_s = timeout_s
        self._pool: ProcessPoolExecutor | None = None

    def _executor(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return self._pool

    def _kill(self) -> None:
        pool, self._pool = self._pool, None
        if pool is None:
            return
        for process in list(getattr(pool, "_processes", {}).values()):  # процесс завис в вёрстке — только kill
            process.kill()
        pool.shutdown(wait=False, cancel_futures=True)

    async def __call__(self, payload: dict[str, Any], logo: bytes | None, logo_mime: str | None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor(), render_payload, payload, logo, logo_mime)
        try:
            return await asyncio.wait_for(future, self._timeout_s)
        except TimeoutError:
            self._kill()
            raise RenderError(TIMEOUT, "process killed") from None
        except RenderError:
            raise
        except Exception as exc:  # процесс пула упал (память, сигнал) — пул пересоздаётся
            self._kill()
            raise RenderError(FAILED, type(exc).__name__) from exc

    def close(self) -> None:
        self._kill()
