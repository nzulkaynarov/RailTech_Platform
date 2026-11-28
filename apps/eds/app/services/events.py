"""Сборка и публикация событий EDS (`uz.railtech.eds.*.v1`): тела — по схемам `packages/contracts/events/eds/`.

Публикует только сервисный слой, в транзакции изменения (`AsyncBus.publish`, CONVENTIONS.md §2 п. 3):
откат — события нет. Тело проверяется библиотекой по схеме строго до записи в outbox.
"""

import uuid
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "uz.railtech.eds."


def actor(crm_user_id: int | None) -> dict[str, Any]:
    """`Actor` события: сотрудник или система EDS (обработчик шины, задача)."""
    if crm_user_id is None:
        return {"type": "system"}
    return {"type": "staff", "crm_user_id": crm_user_id}


def erp_links(
    *,
    erp_request_id: int | None,
    erp_deal_id: int | None,
    deal_number: str | None,
    crm_client_id: int | None,
    erp_company_id: int | None,
) -> dict[str, Any]:
    return {
        "erp_request_id": erp_request_id,
        "erp_deal_id": erp_deal_id,
        "deal_number": deal_number,
        "crm_client_id": crm_client_id,
        "erp_company_id": erp_company_id,
    }


# Типы с номером реестра — v2: обозначение из настроек нумерации (задача «Н», 2026-11-13); подписчики принимают v1 и v2.
VERSION = dict.fromkeys(
    (
        "letter.registered",
        "letter.resolved",
        "letter.returned",
        "letter.rejected",
        "document.registered",
        "document.archived",
        "document.signed",
        "approval.requested",
        "approval.decided",
        "notice.requested",
        "document.notice_requested",  # ГЛ-0, ГЛ-1, ГЛ-2: v2 — все виды уведомлений о документе
    ),
    2,
)


NOTICE_EVENTS = frozenset({"notice.requested", "document.notice_requested", "signing_authority.expiring"})


async def _of_test_company(session: AsyncSession, data: dict[str, Any]) -> bool:
    """Объект уведомления (письмо, исходящий документ, маршрут) принадлежит тестовой компании."""
    from sqlalchemy import select

    from app.models.approvals import ApprovalRoute
    from app.models.documents import Document
    from app.models.letters import Letter
    from app.services import test_companies

    company: int | None = None
    letter, document, approval = data.get("letter"), data.get("document"), data.get("approval")
    if isinstance(letter, dict) and letter.get("eds_letter_id"):
        company = await session.scalar(
            select(Letter.erp_company_id).where(Letter.id == uuid.UUID(str(letter["eds_letter_id"])))
        )
    if company is None and isinstance(approval, dict) and approval.get("eds_approval_id"):
        company = await session.scalar(
            select(ApprovalRoute.erp_company_id).where(ApprovalRoute.id == uuid.UUID(str(approval["eds_approval_id"])))
        )
    if company is None and isinstance(document, dict) and document.get("eds_document_id"):
        company = await session.scalar(
            select(Document.recipient_company_id).where(Document.id == uuid.UUID(str(document["eds_document_id"])))
        )
    return bool(await test_companies.marked(session, test_companies.ALL, [company]))


async def publish(
    bus: AsyncBus, session: AsyncSession, name: str, data: dict[str, Any], *, subject: str | uuid.UUID
) -> None:
    """Событие `uz.railtech.eds.<name>.v<N>` в outbox транзакции `session`; `subject` — номер или id объекта.
    Типы с номером реестра — v2 (задача «Н»): шаблон v1 знает только прежние ВХ, ИСХ, СЗ, ЗЯ, ОТ.

    ТЕСТ-2, шлюз доставки: уведомление сотрудникам (`NOTICE_EVENTS`) о записи тестовой компании несёт `is_test: true` —
    колокольчик и Telegram получат только те, у кого включено «Показывать тестовые» (решает CRM). Одно место для всех
    уведомлений EDS; охранный тест — `tests/test_delivery_guard.py`."""
    if name in NOTICE_EVENTS and await _of_test_company(session, data):
        data = {**data, "is_test": True}
    await bus.publish(session, f"{PREFIX}{name}.v{VERSION.get(name, 1)}", data, subject=str(subject))
