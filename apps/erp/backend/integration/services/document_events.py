"""Событие `document.created` (FIX-38) на шину rt_bus: клиенту выпущен документ (B3).

Шесть источников документов портала — КП, договор, счёт, акт, накладная (`Fulfillment`), `GeneratedDocument`. Событие
рождается на переходе «не выпущен → выпущен» (правило `portal.services.documents.is_issued`, единое с порталом) и только
в сервисе, который этот переход делает, в его транзакции: `with watch_document_issue("contract", contract): …`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from rt_bus import Event

from .events import publish_event

logger = logging.getLogger(__name__)


def publish_document_created(document: Any, actor: Optional[Dict[str, Any]] = None) -> Optional[Event]:
    """Событие `document.created`: клиенту выпущен документ (FIX-38).

    `document` — `portal.services.documents.PortalDocument`, то есть уже выпущенный и видимый клиенту документ;
    `erp_document_id` — его идентификатор портала (тот же, что в `GET /deals/{id}/documents` и у ссылки на файл),
    `kind` — вид документа (КП, договор, счёт, акт, накладная). Черновики и внутренние документы сюда не попадают:
    их отсекает `publish_document_issued` по правилу выпуска портала.
    """
    deal = document.deal
    contact = getattr(document.obj, "contact", None) if deal is None else None
    company_id = deal.company_id if deal is not None else getattr(contact, "company_id", None)
    if not company_id:
        logger.warning("Документ #%s без компании клиента: событие document.created не публикуется", document.id)
        return None

    payload: Dict[str, Any] = {
        "erp_document_id": document.id,
        "kind": document.kind,
        "number": document.number or f"DOC-{document.id}",
    }
    if document.title:
        payload["title"] = document.title

    return publish_event("document.created", erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


def _document_company(source: str, instance: Any):
    """Компания клиента, которой принадлежит документ: по сделке, у `GeneratedDocument` без сделки — по контакту."""
    if instance.deal_id and instance.deal.company_id:
        return instance.deal.company
    if source == "generated" and instance.contact_id and instance.contact.company_id:
        return instance.contact.company
    return None


def document_was_issued(source: str, instance: Any) -> bool:
    """Выпущен ли документ клиенту до изменения (для новой записи — нет). Снимок берут ДО смены статуса."""
    from portal.services import documents as portal_documents

    return bool(instance.pk) and portal_documents.is_issued(source, instance)


def publish_document_issued(source: str, instance: Any, *, was_issued: bool) -> Optional[Event]:
    """`document.created`, когда документ стал выпущенным (и только на этом переходе); иначе `None`.

    Правило выпуска — единое с порталом (`portal.services.documents.is_issued`): черновики, КП до отправки, отменённые
    документы, письма и рапорты событий не дают. Скан подписанного акта (входящий файл клиента) — не документ ERP.
    `source` — `quote`, `contract`, `invoice`, `act`, `waybill` (накладная — `Fulfillment`) или `generated`.
    """
    from portal.services import documents as portal_documents

    if was_issued or not portal_documents.is_issued(source, instance):
        return None
    if source == "generated" and portal_documents.is_portal_scan(instance):
        return None
    company = _document_company(source, instance)
    if company is None:
        return None
    document = portal_documents.find_client_document(company, portal_documents.encode_document_id(source, instance.pk))
    if document is None:
        return None
    return publish_document_created(document)


@contextmanager
def watch_document_issue(source: str, instance: Any) -> Iterator[None]:
    """`with watch_document_issue("contract", contract): …смена статуса и save()…` — `document.created` на переходе
    «не выпущен → выпущен». Снимок «был выпущен» берётся до блока, событие — после него, в той же транзакции."""
    was_issued = document_was_issued(source, instance)
    yield
    publish_document_issued(source, instance, was_issued=was_issued)
