"""Когда состав и цены КП можно править (FIX-55, D-04).

Позиции и статьи расходов КП несут цены, поэтому правятся только в черновике (`DRAFT`) и пока КП не
заморожено отправкой клиенту (`frozen_at`). На согласовании (`PENDING_TRADE_REVIEW`,
`PENDING_APPROVAL`), в `READY_TO_SEND`, после отправки (`SENT`), акцепта (`APPROVED`) и отказа
(`REJECTED`) — 409. Путь к правке: отзыв / возврат на доработку (в `DRAFT`) или новая версия КП.

Один хелпер на все пути записи: single CRUD позиций и статей, bulk-операции, перепривязка товара,
импорт строк, порядок и базис, PATCH КП. Коды — как у `sales.services.quote_fx`.
"""

from typing import Optional

from rest_framework import status
from rest_framework.exceptions import APIException

from crm.constants import QuoteStatusCode

QUOTE_FROZEN = "QUOTE_FROZEN"
QUOTE_NOT_DRAFT = "QUOTE_NOT_DRAFT"


class QuoteLockedError(APIException):
    """409 `{"detail": "<CODE>"}`: КП нельзя править в текущем статусе (QUOTE_NOT_DRAFT / QUOTE_FROZEN)."""

    status_code = status.HTTP_409_CONFLICT
    default_code = QUOTE_NOT_DRAFT

    def __init__(self, code: str):
        super().__init__(detail=code, code=code)
        self.code = code


def quote_edit_lock_code(quote) -> Optional[str]:
    """Код блокировки правки КП или None, если КП можно править.

    Сначала заморозка (`frozen_at` — КП ушло клиенту), затем статус: КП без статуса считается черновиком
    (как `rates_are_live`)."""
    if quote.frozen_at is not None:
        return QUOTE_FROZEN
    quote_status = quote.status if quote.status_id else None
    if quote_status is not None and quote_status.code != QuoteStatusCode.DRAFT:
        return QUOTE_NOT_DRAFT
    return None


def assert_quote_items_editable(quote) -> None:
    """Бросает `QuoteLockedError` (409), если позиции/расходы КП править нельзя."""
    code = quote_edit_lock_code(quote)
    if code:
        raise QuoteLockedError(code)
