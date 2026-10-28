"""Рендер PDF через WeasyPrint: изолированные шрифты, безопасный fetcher, статистика страниц, тайм-аут,
«Стр. N из M» только при M > 1.

Импорт этого модуля требует системных библиотек WeasyPrint (pango, harfbuzz): в сервисе — образ потребителя,
в тестах — docker/test.Dockerfile. Остальной пакет (схема, HTML, DOCX, форматтеры) работает без них.
Изоляция шрифтов и статистика страниц опираются на внутренности WeasyPrint 69 — другая версия отклоняется при импорте.
"""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import weasyprint

from .engine import check_weasyprint_version

check_weasyprint_version(weasyprint.__version__)

from weasyprint import HTML  # noqa: E402 — только после проверки версии
from weasyprint.formatting_structure import boxes  # noqa: E402
from weasyprint.text.ffi import ffi, fontconfig, gobject, pangoft2  # noqa: E402
from weasyprint.text.fonts import FontConfiguration  # noqa: E402
from weasyprint.urls import URLFetcher, URLFetcherResponse  # noqa: E402

from .contracts import Catalog  # noqa: E402
from .css import PageSetup  # noqa: E402
from .errors import RenderTimeoutError  # noqa: E402
from .fetcher import ResourcePolicy  # noqa: E402
from .model import DocumentMeta, Layout, Letterhead, PageStats, RenderResult, Tuning, Value  # noqa: E402
from .prepare import Prepared, document_html, prepare  # noqa: E402

__all__ = ["Prepared", "RenderTimeoutError", "measure", "prepare", "render_pdf", "render_prepared"]

#: Тайм-аут рендера по умолчанию, с: счёт на 500 позиций укладывается с запасом; сервисы зовут рендер в воркере.
DEFAULT_TIMEOUT_S = 60.0

# FcConfigCreate нет в объявлениях cffi WeasyPrint — объявляем один раз при импорте модуля (ABI-режим разрешает cdef
# после dlopen; импорт идёт под блокировкой импорта, поэтому потоки сервера не объявят его дважды).
ffi.cdef("FcConfig * FcConfigCreate (void);")


class IsolatedFontConfiguration(FontConfiguration):  # type: ignore[misc]
    """Конфигурация fontconfig без системных шрифтов: документ видит только @font-face пакета.

    WeasyPrint строит конфигурацию из системной (FcInitLoadConfigAndFonts) — DejaVu, PT Sans и всё, что стоит в образе,
    участвовало бы в подборе запасного шрифта, и число страниц зависело бы от образа. Здесь карта шрифтов Pango получает
    пустую конфигурацию (FcConfigCreate); @font-face WeasyPrint добавляет в неё вшитые файлы (add_font_face). Тело
    __init__ повторяет WeasyPrint 69 (внутренние имена _config, font_map, _folder проверяют тесты при смене версии).
    """

    def __init__(self) -> None:
        self._config = ffi.gc(fontconfig.FcConfigCreate(), fontconfig.FcConfigDestroy)
        self.font_map = ffi.gc(pangoft2.pango_ft2_font_map_new(), gobject.g_object_unref)
        pangoft2.pango_fc_font_map_set_config(ffi.cast("PangoFcFontMap *", self.font_map), self._config)
        # Тот же учёт ссылок, что в WeasyPrint: ссылку держит карта шрифтов.
        fontconfig.FcConfigDestroy(self._config)
        self._folder = None
        self.strut_layouts: dict[Any, Any] = {}
        self.font_features: dict[Any, Any] = {}


class SafeURLFetcher(URLFetcher):  # type: ignore[misc]
    """URL fetcher WeasyPrint по белому списку `ResourcePolicy`: без сети и без файловой системы."""

    def __init__(self, policy: ResourcePolicy) -> None:
        super().__init__(allowed_protocols=())
        self.policy = policy

    def fetch(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        resource = self.policy.resolve(url)
        if resource is None:
            raise ValueError(f"rt_docs: resource is not allowed: {url[:80]}")
        return URLFetcherResponse(url, resource.data, {"Content-Type": resource.mime})


def page_stats(document: Any) -> PageStats:
    """Число страниц и заполненность последней: низ самого нижнего бокса потока / высота области текста."""
    pages = document.pages
    page_box = pages[-1]._page_box
    top = page_box.content_box_y()
    height = page_box.height
    root = page_box.children[0]
    bottom = top
    for box in root.descendants():
        if box is root or getattr(box, "element_tag", None) in ("html", "body", "main"):
            continue
        if isinstance(box, boxes.MarginBox) or box.style["position"] not in ("static", "relative"):
            continue
        if isinstance(box, boxes.BlockBox | boxes.TableBox) and box.children:
            continue  # контейнер: считаем по содержимому (его нижнее поле не текст)
        bottom = max(bottom, box.position_y + box.margin_top + box.border_height())
    fill = max(0.0, min(1.0, (bottom - top) / height)) if height else 0.0
    return PageStats(pages=len(pages), last_page_fill=round(fill, 4))


class _Interrupted(BaseException):
    """Сигнал тайм-аута внутри WeasyPrint: BaseException, чтобы его не проглотили `except Exception` движка."""


class Deadline:
    """Тайм-аут рендера: жёсткий (SIGALRM) в главном потоке, мягкий (проверка между проходами) — в остальных."""

    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds
        self.until = time.monotonic() + seconds if seconds else None

    def check(self) -> None:
        if self.until is not None and time.monotonic() >= self.until:
            raise RenderTimeoutError(self.seconds or 0)

    @contextmanager
    def armed(self) -> Iterator[Deadline]:
        if not self.seconds or threading.current_thread() is not threading.main_thread():
            yield self
            return

        def interrupt(_signum: int, _frame: Any) -> None:
            raise _Interrupted

        previous = signal.signal(signal.SIGALRM, interrupt)
        outer, _ = signal.setitimer(signal.ITIMER_REAL, self.seconds)
        started = time.monotonic()
        try:
            yield self
        except _Interrupted:
            raise RenderTimeoutError(self.seconds) from None
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if outer:  # чужой таймер процесса — вернуть остаток
                signal.setitimer(signal.ITIMER_REAL, max(0.001, outer - (time.monotonic() - started)))


@dataclass(frozen=True)
class Measured:
    """Один проход вёрстки без номеров страниц: разбивка и статистика (номера на поток не влияют)."""

    tuning: Tuning
    setup: PageSetup
    document: Any
    policy: ResourcePolicy
    stats: PageStats


def _layout(prepared: Prepared, tuning: Tuning, *, page_numbers: bool) -> tuple[Any, ResourcePolicy]:
    policy = ResourcePolicy(logo=prepared.letterhead.logo)
    html = document_html(prepared, tuning, page_numbers=page_numbers)
    document = HTML(string=html, base_url=None, url_fetcher=SafeURLFetcher(policy)).render(
        font_config=IsolatedFontConfiguration()
    )
    return document, policy


def measure(prepared: Prepared, tuning: Tuning | None, deadline: Deadline) -> Measured:
    """Проход вёрстки для статистики (кандидаты «Подогнать» и первый проход итогового рендера)."""
    deadline.check()
    effective = tuning if tuning is not None else prepared.tuning
    document, policy = _layout(prepared, effective, page_numbers=False)
    return Measured(effective, prepared.setup(effective), document, policy, page_stats(document))


def finish(prepared: Prepared, measured: Measured, deadline: Deadline, passes: int) -> RenderResult:
    """PDF из измеренного прохода; при двух и более страницах — ещё один проход с «Стр. N из M» (разбивка та же)."""
    document, policy, stats = measured.document, measured.policy, measured.stats
    if stats.pages > 1:
        deadline.check()
        document, policy = _layout(prepared, measured.tuning, page_numbers=True)
        stats = page_stats(document)
        passes += 1
    deadline.check()
    pdf = document.write_pdf()
    used = replace(measured.tuning, density=measured.setup.density, line_height=measured.setup.line_height)
    blocked = tuple(dict.fromkeys([*measured.policy.blocked, *policy.blocked]))
    return RenderResult(pdf, stats, used, prepared.warnings, blocked, passes)


def render_prepared(
    prepared: Prepared, tuning: Tuning | None = None, *, timeout_s: float | None = DEFAULT_TIMEOUT_S
) -> RenderResult:
    """Рендер подготовленного тела с подстройкой `tuning` (по умолчанию — из `page.tuning` тела)."""
    deadline = Deadline(timeout_s)
    with deadline.armed():
        return finish(prepared, measure(prepared, tuning, deadline), deadline, passes=1)


def render_pdf(
    body: Mapping[str, Any],
    *,
    letterhead: Letterhead,
    layout: Layout,
    meta: DocumentMeta | None = None,
    values: Mapping[str, Value] | None = None,
    blocks: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    tuning: Tuning | None = None,
    catalog: Catalog | None = None,
    highlight_missing: bool = True,
    contracts_dir: str | None = None,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> RenderResult:
    """Тело документа (контракт documents/body.schema.json) → PDF на бланке со статистикой страниц.

    `timeout_s` — предел всего рендера; превышен — `RenderTimeoutError` (вызывающий показывает понятную ошибку).
    """
    prepared = prepare(
        body,
        letterhead=letterhead,
        layout=layout,
        meta=meta,
        values=values,
        blocks=blocks,
        catalog=catalog,
        highlight_missing=highlight_missing,
        contracts_dir=contracts_dir,
    )
    return render_prepared(prepared, tuning, timeout_s=timeout_s)


def render_html_unsafe_for_tests(html: str) -> tuple[bytes, tuple[str, ...]]:
    """Рендер произвольного HTML с тем же fetcher'ом и шрифтами — только для тестов защиты (file://, http://)."""
    policy = ResourcePolicy()
    document = HTML(string=html, base_url=None, url_fetcher=SafeURLFetcher(policy)).render(
        font_config=IsolatedFontConfiguration()
    )
    return document.write_pdf(), tuple(policy.blocked)
