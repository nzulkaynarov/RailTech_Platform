"""«ПРОЕКТ» на документе до выпуска — один механизм для КП, договора, счёта, акта и письма (SIGN-1, ADR-0024 п. 4).

Любой PDF на бланке, который ещё не выпущен (КП до заморозки, договор, счёт и акт в черновике, письмо-черновик),
строится с `document_draft=True` в контексте шаблона `_document_base.html`: диагональный знак «ПРОЕКТ» на каждой
странице, вместо номера и даты «без номера», в колонтитуле «Проект — не является официальным документом». Выпущенный
документ — без знака, как прежде. Подпись и печать ставит отдельный шаг (следующая задача) — до него документ проект.

Кэш PDF в `pdf_file` (рендер идёт в фоне и хранится; имя файла хранилище задаёт само): в каком виде построен файл, рендер
запоминает в кэше Django (`remember_pdf_state`), а скачивание не отдаёт «проект без знака» и «знак на выпущенном» —
перерисовывает (`pdf_is_stale`).
"""

from __future__ import annotations

from typing import Any

from crm.constants import ActStatusCode, ContractStatusCode, GeneratedDocumentStatusCode, InvoiceStatusCode



def draft_context(is_draft: bool, *, offer: bool = False) -> dict[str, Any]:
    """Поля контекста шаблона `_document_base.html`; для выпущенного документа — без знака.

    `offer=True` (КП) — под знаком «не является офертой»: прежняя формулировка плашки «ЧЕРНОВИК · не является офертой».
    """
    return {"document_draft": bool(is_draft), "document_draft_offer": bool(is_draft and offer)}


def quote_is_draft(quote) -> bool:
    """КП — оферта только после заморозки на отправке."""
    return quote.frozen_at is None


def contract_is_draft(contract) -> bool:
    return contract.status_code == ContractStatusCode.DRAFT


def invoice_is_draft(invoice) -> bool:
    return invoice.status_code == InvoiceStatusCode.DRAFT


def act_is_draft(act) -> bool:
    """Черновик у акта — возврат заказчиком до повторного выпуска."""
    return act.status_code == ActStatusCode.DRAFT


def generated_is_draft(document) -> bool:
    return document.status_code == GeneratedDocumentStatusCode.DRAFT


#: Сколько помним, в каком виде построен кэшированный PDF.
_STATE_TTL = 30 * 24 * 3600


def _state_key(doc_type: str, pk: int) -> str:
    return f"pdf-draft-state:{doc_type}:{pk}"


def remember_pdf_state(doc_type: str, pk: int, is_draft: bool) -> None:
    """Рендер записал PDF проекта (`draft`) или выпущенного (`final`) — запомнить для `pdf_is_stale`."""
    from django.core.cache import cache

    cache.set(_state_key(doc_type, pk), "draft" if is_draft else "final", _STATE_TTL)


def pdf_is_stale(doc_type: str, pk: int, pdf_file, is_draft: bool) -> bool:
    """Кэшированный PDF не соответствует состоянию документа — отдавать его нельзя, нужен рендер.

    Проект без записи о рендере со знаком (построен до SIGN-1, до отката в черновик или запись потеряна) — устарел;
    знак проекта на уже выпущенном (выпуск ещё не перерисован) — тоже. Выпущенный без записи — как прежде, отдаётся.
    """
    if not pdf_file:
        return False
    from django.core.cache import cache

    state = cache.get(_state_key(doc_type, pk))
    return (state == "draft") != bool(is_draft) if state is not None else bool(is_draft)
