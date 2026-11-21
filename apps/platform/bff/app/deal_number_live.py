"""Текущий номер сделки из ERP по её идентификатору.

Заявка после принятия КП становится проектом и получает другой номер; перенумерация тоже меняет
номера. Копия номера, сохранённая в EDS (`deal_number`), устаревает, поэтому карточки показывают
номер, который сейчас отдаёт ERP. ERP не ответил или номера нет — остаётся сохранённая копия.
"""

from typing import Any

from app.deps import Authed
from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed
from app.feeds.snapshot import DEALS_PATH


def number_of(deal: Any, stored: str | None) -> str | None:
    """Номер из ответа ERP; нет — сохранённая копия."""
    if isinstance(deal, dict):
        own = deal.get("number")
        if isinstance(own, str) and own:
            return own
    return stored


async def live_deal_number(authed: Authed, deal_id: int | None, stored: str | None) -> str | None:
    if deal_id is None:
        return stored
    deal = await Feed(authed).get("erp", f"{DEALS_PATH}{deal_id}/", ttl=SNAPSHOT_TTL_SECONDS)
    return number_of(deal, stored)


async def with_live_deal_number(authed: Authed, raw: Any) -> Any:
    """Копия ответа EDS (документ), где `deal_number` заменён текущим номером из ERP."""
    if not isinstance(raw, dict):
        return raw
    deal_id = raw.get("erp_deal_id")
    if not isinstance(deal_id, int):
        return raw
    stored = raw.get("deal_number")
    number = await live_deal_number(authed, deal_id, stored if isinstance(stored, str) else None)
    return {**raw, "deal_number": number}
