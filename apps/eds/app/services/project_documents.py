"""Документы проектов в реестре (D2-5): проекция договоров, счетов и актов ERP по событиям шины.

`apply` — идемпотентный upsert по `(kind, erp_id)`: повтор безвреден, более старое событие (по `time` конверта) не
перезаписывает более новое. Название строки — название сделки (`DealRef.title`), клиент и ответственный берутся из
письма по той же заявке (`letters.erp_deal_id`): проекту ERP они известны только через него. Статус — слово SPEC-v3
§2.4: договор — как прислал ERP, счёт — `issued`/`paid`/`overdue` по типу события, акт — `issued`/`signed`/`returned`.
События не публикуются: реестр — чтение, решений здесь нет.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_snapshots import ProjectDocumentEvent
from app.models import Letter, ProjectDocument

#: Тип события ERP → (вид документа, статус по типу; `None` — статус в `payload`).
EVENT_STATUS: dict[str, tuple[str, str | None]] = {
    "uz.railtech.erp.contract.status_changed.v1": ("contract", None),
    "uz.railtech.erp.invoice.issued.v1": ("invoice", "issued"),
    "uz.railtech.erp.invoice.paid.v1": ("invoice", "paid"),
    "uz.railtech.erp.invoice.overdue.v1": ("invoice", "overdue"),
    "uz.railtech.erp.act.issued.v1": ("act", "issued"),
    "uz.railtech.erp.act.accepted.v1": ("act", "signed"),
    "uz.railtech.erp.act.returned.v1": ("act", "returned"),
}


@dataclass(frozen=True)
class Source:
    """Что известно о документе из события."""

    kind: str
    erp_id: int
    number: str
    status: str
    amount: Decimal | None
    currency: str | None


def _amount(value: str | None) -> Decimal | None:
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


def source_of(event_type: str, data: ProjectDocumentEvent) -> Source | None:
    """Вид, id в ERP, номер и статус документа; `None` — событие не про документ проекта или без id/статуса."""
    spec = EVENT_STATUS.get(event_type)
    if spec is None:
        return None
    kind, fixed = spec
    payload = data.payload
    erp_id = {"contract": payload.erp_contract_id, "invoice": payload.erp_invoice_id, "act": payload.erp_act_id}[kind]
    status = fixed or payload.status
    if erp_id is None or status is None:
        return None
    return Source(kind, erp_id, payload.number, status, _amount(payload.amount), payload.currency)


async def _who(session: AsyncSession, erp_deal_id: int) -> tuple[str | None, str | None, int | None]:
    """Клиент и менеджер проекта — из письма по заявке (первого по времени регистрации); письма нет — пусто."""
    row = (
        await session.execute(
            select(Letter.sender_name, Letter.sender_inn, Letter.manager_crm_user_id)
            .where(Letter.erp_deal_id == erp_deal_id)
            .order_by(Letter.registered_at)
            .limit(1)
        )
    ).first()
    return (row.sender_name, row.sender_inn, row.manager_crm_user_id) if row else (None, None, None)


async def apply(
    session: AsyncSession, event_type: str, data: ProjectDocumentEvent, *, moment: datetime
) -> ProjectDocument | None:
    """Записать документ проекта; `None` — событие не про документ проекта или оно старее уже применённого."""
    source = source_of(event_type, data)
    if source is None:
        return None
    client_name, client_inn, responsible = await _who(session, data.deal.erp_deal_id)
    values = {
        "kind": source.kind,
        "erp_id": source.erp_id,
        "number": source.number[:64],
        "title": (data.deal.title or f"Проект {data.deal.number}")[:300],
        "status": source.status,
        "amount": source.amount,
        "currency": source.currency,
        "erp_deal_id": data.deal.erp_deal_id,
        "deal_number": data.deal.number[:64],
        "erp_company_id": data.erp_company_id,
        "crm_client_id": data.crm_client_id,
        "client_name": client_name,
        "client_inn": client_inn,
        "responsible_crm_user_id": responsible,
        "registered_at": moment,
        "updated_at": moment,
    }
    insert_stmt = insert(ProjectDocument).values(**values)
    keep = {"registered_at", "kind", "erp_id"}  # дата регистрации — первого события, ключ не меняется
    upsert = insert_stmt.on_conflict_do_update(
        constraint="uq_project_documents_kind_erp_id",
        set_={k: insert_stmt.excluded[k] for k in values if k not in keep},
        where=ProjectDocument.updated_at <= insert_stmt.excluded.updated_at,
    ).returning(ProjectDocument.id)
    applied = (await session.execute(upsert)).scalar_one_or_none()
    if applied is None:
        return None
    return await session.get(ProjectDocument, applied, populate_existing=True)
