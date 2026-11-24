"""Логотип компании в строках реестров (ЕД-3, ЕД-5): один пакетный запрос на список.

Строки проектов, счетов и писем приходят из EDS/ERP с названием клиента и его id компании ERP.
Версии логотипов BFF берёт у ERP пачками (`logo_urls`, до 100 id за запрос, повторы схлопнуты) и
кладёт в строку наш путь `…/logo?v=`; адресов хранилища наружу нет. Нет права на раздел, ERP не
ответил или логотипа нет — поле пустое, клиент рисует буквы названия: картинка не ломает реестр.
"""

from collections.abc import Iterable
from typing import Protocol

from app.api.people_pictures import LOGO_SECTIONS, logo_urls
from app.deps import Authed
from app.rbac import allows


class WithClient(Protocol):
    client_id: int | None
    client_logo_url: str | None


async def attach_client_logos(authed: Authed, rows: Iterable[WithClient]) -> None:
    """Проставляет `client_logo_url` строкам с `client_id`; ERP — пачками на весь список."""
    batch = [r for r in rows if r.client_id]
    if not batch or not any(allows(authed.access, res, need) for res, need in LOGO_SECTIONS):
        return
    urls = await logo_urls(authed, [r.client_id for r in batch if r.client_id])
    for r in batch:
        r.client_logo_url = urls.get(r.client_id or 0)
