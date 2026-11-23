"""Что гость видит в документе по ссылке — клиентская проекция КП (без себестоимости, наценки и внутренних полей)."""

from __future__ import annotations

from typing import Optional

from portal import projections


def newer_sent_version(quote) -> Optional[int]:
    from portal.public_views import _newer_sent_version

    return _newer_sent_version(quote)


def document_state(quote) -> str:
    """`open` — ждёт ответа; `accepted`, `rejected`, `expired` — решено или срок вышел (из фактов КП, не из ссылки)."""
    status = projections.quote_status(quote)
    return "open" if status in ("sent", "viewed") else status
