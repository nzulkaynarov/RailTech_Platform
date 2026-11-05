"""Запрос клиента из Cabinet (`POST /requests`, FIX-23, P-15).

Запрос и сделка — одна запись `sales.Deal` (Q-16): портал создаёт её на стадии «черновик» со строками
(`PortalRequestLine`), полным текстом (`PortalRequestSummary`, до 5000 знаков — `Deal.title` держит 255) и вложениями
из `PortalUpload`. Ничего не подставляется за клиента: количество и единица — как указал клиент или пусто.

Всё делается одной транзакцией: плохое вложение отклоняет запрос целиком, и от него не остаётся ни сделки, ни строк,
ни события. Событие `request.created` с `source=cabinet` этот сервис публикует на шину rt_bus в той же транзакции
(`integration.services.events`): сбой публикации откатывает запрос. Источник решает создатель сделки — контакт портала у
сделки не доказывает, что её завёл портал: контакт ставит и сотрудник.
"""

from __future__ import annotations

import uuid

from django.core.files import File
from django.db import transaction
from integration.services import events, partner_client
from portal.exceptions import PortalValidationError
from portal.models import PortalRequestLine, PortalRequestSummary, PortalUpload

from crm.constants import DealStageCode
from crm.models import ActivityLog, Deal, DealStage
from sourcing.models import Attachment

REQUEST_SOURCE = "cabinet"


def short_title(summary: str) -> str:
    """Название сделки из сути запроса: одна строка, не длиннее поля `Deal.title`."""
    title = " ".join(summary.split())
    max_length = Deal._meta.get_field("title").max_length
    return title if len(title) <= max_length else title[: max_length - 1].rstrip() + "…"


def _lock_uploads(company, refs: list[dict]) -> list[PortalUpload]:
    """Загрузки компании по `upload_id` вложений, ещё не привязанные к запросу; неизвестная — `UPLOAD_NOT_FOUND`.

    Строки блокируются до конца транзакции: один файл не уйдёт в два запроса одновременно.
    """
    wanted: dict[uuid.UUID, None] = {}
    for ref in refs:
        try:
            wanted[uuid.UUID(ref["upload_id"])] = None
        except ValueError:
            raise PortalValidationError("UPLOAD_NOT_FOUND") from None
    uploads = list(
        PortalUpload.objects.select_for_update().filter(upload_id__in=list(wanted), company=company, deal__isnull=True)
    )
    if len(uploads) != len(wanted):
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    return uploads


def _attach(deal: Deal, upload: PortalUpload) -> None:
    """Файл загрузки — вложением сделки: копия в приватное хранилище сделок, а не общая ссылка на чужой путь."""
    upload.deal = deal
    upload.save(update_fields=["deal"])
    with upload.file.open("rb") as source:
        Attachment(deal=deal, original_filename=upload.name, kind="SOURCE").file.save(
            upload.name, File(source), save=True
        )


def create_client_request(company, contact, *, summary: str, lines: list[dict], attachments: list[dict]) -> Deal:
    """Создаёт запрос клиента; вернуть сделку. Данные уже прошли `ClientRequestCreateSerializer`."""
    draft_stage = DealStage.objects.filter(code=DealStageCode.DRAFT).first()
    with transaction.atomic():
        # Партнёр: ответ CRM «клиент заведён» (`partner.client_resolved`) и эта заявка идут по очереди — иначе заявка, созданная
        # между проверкой сопоставления и записью отложенного события, осталась бы неопубликованной навсегда.
        partner_client.lock_if_partner(company)
        uploads = _lock_uploads(company, attachments)
        deal = Deal(
            company=company,
            contact=contact,
            title=short_title(summary),
            stage=draft_stage,
            notes="Запрос создан клиентом из Cabinet",
        )
        deal.save()
        PortalRequestSummary.objects.create(deal=deal, text=summary)
        PortalRequestLine.objects.bulk_create(
            PortalRequestLine(
                deal=deal,
                text=line["text"],
                quantity=line.get("quantity"),
                unit=(line.get("unit") or "").strip(),
                sort_order=position,
            )
            for position, line in enumerate(lines, start=1)
        )
        for upload in uploads:
            _attach(deal, upload)
        ActivityLog.objects.create(
            deal=deal,
            action="Создан запрос",
            event_code="deal.created",
            detail=f"Клиент создал запрос из Cabinet: {summary}",
            event_params={"source": REQUEST_SOURCE, "contact_id": contact.id},
        )
        event = events.publish_request_created(deal, source=REQUEST_SOURCE, erp_request_id=deal.id, summary=summary)
        if event is None:
            _notify_unrouted_partner_request(company, deal, summary)
    return deal


PARTNER_REQUEST_NOTIFY_EVENT = "portal.partner_request_unrouted"


def _notify_unrouted_partner_request(company, deal: Deal, summary: str) -> None:
    """Заявка партнёра, чья компания ещё не сопоставлена клиенту CRM, в CRM не попала (`request.created` несёт только
    привязанных клиентов, CONTRACTS §3): уведомляем ответственного сотрудника отношения, чтобы она не потерялась, и
    откладываем событие (`DeferredRequestEvent`) — как только CRM заведёт клиента (`partner.client_resolved`, PART-CRM),
    ERP опубликует его сама. Ответственного нет — уведомление получают администраторы платформы."""
    from parties.models import CompanyRelationship, RelationshipRole

    from notifications.services import notify_platform_admins, notify_user

    relationship = (
        CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER)
        .select_related("responsible")
        .first()
    )
    if relationship is None:
        return  # не партнёр: прежнее поведение (клиента без сопоставления CRM заводит передача из CRM)
    from integration.models import DeferredRequestEvent

    DeferredRequestEvent.objects.get_or_create(deal=deal)
    params = {"company": company.name, "deal_id": deal.pk}
    title = f"Заявка партнёра «{company.name}» ждёт клиента в CRM"
    message = (
        f"Партнёр создал заявку из кабинета: {summary[:300]}. Компания ещё не стала клиентом CRM, поэтому заявка пока "
        "только в ERP: как только CRM заведёт клиента, заявка уйдёт менеджеру сама. Не дождались — откройте карточку "
        "поставщика, блок «Доступ в кабинет»: там видно, заведён ли клиент в CRM или есть конфликт."
    )
    if relationship.responsible_id:
        notify_user(
            user=relationship.responsible,
            title=title,
            message=message,
            deal=deal,
            type_code="WARNING",
            event_code=PARTNER_REQUEST_NOTIFY_EVENT,
            event_params=params,
        )
    else:
        notify_platform_admins(
            title=title,
            message=message,
            type_code="WARNING",
            event_code=PARTNER_REQUEST_NOTIFY_EVENT,
            event_params=params,
        )
