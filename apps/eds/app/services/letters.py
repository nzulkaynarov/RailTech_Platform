"""Входящие письма и резолюции (SPEC-v3 §2.4, §7.3; eds.yaml, таблица переходов в `info.description`).

Регистрация (вручную или по `erp.request.created`) даёт номер `ВХ-NNN/ГГ` и статус `awaiting_resolution`; директор
накладывает резолюцию, возвращает регистратору или отклоняет; возвращённое подаётся снова с тем же номером.
Каждая операция — одна транзакция: изменение, строка журнала и событие шины (`letter.*`) вместе.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, invalid_fields, not_found
from app.models import Letter
from app.schemas.common import ErpLinksIn
from app.schemas.letters import LetterCreate, LetterStatus, LetterSubmitIn, ResolutionIn
from app.services import events, files, journal, numbering
from app.services.people import active_ids, default_director, load_directory

log = structlog.get_logger(__name__)

_INN = re.compile(r"^\d{9,14}$")


@dataclass(frozen=True)
class RequestParties:
    """Отправитель и менеджер письма по заявке — из `payload` события `erp.request.created` (C1-G-7, 2026-10-26).

    Поля необязательные: старое событие без них даёт письмо без отправителя по имени и без менеджера.
    """

    company_name: str | None = None
    company_inn: str | None = None
    contact_name: str | None = None
    manager_crm_user_id: int | None = None

    def values(self) -> dict[str, Any]:
        """Колонки письма: имя и контакт обрезаются до длины колонок, ИНН берётся, только если похож на ИНН."""
        inn = (self.company_inn or "").strip()
        return {
            "sender_name": (self.company_name or "").strip()[:255] or None,
            "sender_inn": inn if _INN.match(inn) else None,
            "sender_contact": (self.contact_name or "").strip()[:255] or None,
            "manager_crm_user_id": self.manager_crm_user_id,
        }


def fmt_pct(value: Decimal | None) -> str | None:
    """Процент строкой без лишних нулей (`15`, `12.5`) — как в примерах контракта."""
    return None if value is None else format(value.normalize(), "f")


async def get_for_update(session: AsyncSession, letter_id: uuid.UUID) -> Letter:
    letter = (
        await session.execute(select(Letter).where(Letter.id == letter_id).with_for_update())
    ).scalar_one_or_none()
    if letter is None:
        raise not_found("Письмо не найдено.")
    return letter


def _require(letter: Letter, expected: LetterStatus) -> None:
    if letter.status != expected:
        raise conflict(
            "invalid_state",
            "Операция недоступна в текущем статусе письма.",
            status=letter.status,
            expected=expected.value,
        )


def _links(letter: Letter) -> dict[str, Any]:
    return events.erp_links(
        erp_request_id=letter.erp_request_id,
        erp_deal_id=letter.erp_deal_id,
        deal_number=letter.deal_number,
        crm_client_id=letter.crm_client_id,
        erp_company_id=letter.erp_company_id,
    )


def _ref(letter: Letter) -> dict[str, Any]:
    return {"eds_letter_id": str(letter.id), "number": letter.number, "subject": letter.subject}


async def _validate_staff(session: AsyncSession, **ids: int | None) -> None:
    given = {name: uid for name, uid in ids.items() if uid is not None}
    active = await active_ids(session, given.values())
    missing = [name for name, uid in given.items() if uid not in active]
    if missing:
        raise invalid_fields("Сотрудник не найден или отключён.", **dict.fromkeys(missing, "not_active_employee"))


async def _publish_registered(bus: AsyncBus, session: AsyncSession, letter: Letter, actor_id: int | None) -> None:
    director = letter.addressee_crm_user_id or await default_director(session)
    directory = await load_directory(session, [director])
    body: dict[str, Any] = {
        "eds_letter_id": str(letter.id),
        "number": letter.number,
        "subject": letter.subject,
        "received_at": letter.received_at.isoformat(),
        "registered_at": letter.registered_at.isoformat(),
        "sender": {"name": letter.sender_name, "inn": letter.sender_inn},
        "urgent": letter.urgent,
    }
    if letter.sender_contact is not None:
        body["sender"]["contact"] = letter.sender_contact
    if director is not None:
        body["addressee"] = directory.person(director).model_dump()
    data = {"letter": body, "links": _links(letter), "actor": events.actor(actor_id)}
    await events.publish(bus, session, "letter.registered", data, subject=letter.number)


async def _insert(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int | None, values: dict[str, Any], file_ids: list[uuid.UUID]
) -> Letter:
    """Номер, строка письма, вложения, журнал и `letter.registered` — в транзакции вызывающего."""
    now = clock.now()
    if values.get("addressee_crm_user_id") is None:  # адресат по умолчанию фиксируется при регистрации
        values["addressee_crm_user_id"] = await default_director(session)
    letter = Letter(
        id=uuid.uuid4(),
        number=await numbering.allocate(session, numbering.NumberKind.LETTER_IN, now),
        status=LetterStatus.AWAITING_RESOLUTION.value,
        registered_at=now,
        registered_by=actor_id,
        updated_at=now,
        **values,
    )
    session.add(letter)
    await session.flush()
    await journal.record(session, "letter.registered", by=actor_id, letter_id=letter.id)
    if actor_id is not None:
        await files.attach(session, file_ids, actor_id=actor_id, letter_id=letter.id)
    await _publish_registered(bus, session, letter, actor_id)
    log.info("letter_registered", number=letter.number, by=actor_id)
    return letter


def _link_values(links: ErpLinksIn | None) -> dict[str, Any]:
    links = links or ErpLinksIn()
    return {
        "erp_request_id": links.erp_request_id,
        "erp_deal_id": links.erp_deal_id,
        "deal_number": links.deal_number,
        "crm_client_id": links.crm_client_id,
        "erp_company_id": links.erp_company_id,
    }


async def register(session: AsyncSession, bus: AsyncBus, *, actor_id: int, data: LetterCreate) -> Letter:
    """Ручная регистрация (`POST /letters`). Нужен отправитель по имени или клиент CRM в `links`."""
    links = data.links or ErpLinksIn()
    if not data.sender.name and links.crm_client_id is None:
        raise invalid_fields("Укажите отправителя или клиента.", sender="name_or_client_required")
    if links.erp_request_id is not None and await find_by_request(session, links.erp_request_id) is not None:
        raise conflict("letter_exists_for_request", "Письмо по этой заявке уже зарегистрировано.")
    await _validate_staff(
        session, addressee_crm_user_id=data.addressee_crm_user_id, manager_crm_user_id=data.manager_crm_user_id
    )
    ref = data.sender_ref
    values: dict[str, Any] = {
        "subject": data.subject,
        "summary": data.summary,
        "sender_name": data.sender.name,
        "sender_inn": data.sender.inn,
        "sender_contact": data.sender.contact,
        "sender_ref_number": ref.number if ref else None,
        "sender_ref_date": ref.date if ref else None,
        "received_at": data.received_at,
        "addressee_crm_user_id": data.addressee_crm_user_id,
        "manager_crm_user_id": data.manager_crm_user_id,
        "urgent": data.urgent,
        **_link_values(data.links),
    }
    try:
        return await _insert(session, bus, actor_id=actor_id, values=values, file_ids=data.file_ids)
    except IntegrityError as exc:  # гонка с обработчиком `request.created`: заявку уже заняло другое письмо
        raise conflict("letter_exists_for_request", "Письмо по этой заявке уже зарегистрировано.") from exc


async def find_by_request(session: AsyncSession, erp_request_id: int) -> Letter | None:
    return (await session.execute(select(Letter).where(Letter.erp_request_id == erp_request_id))).scalar_one_or_none()


async def register_from_request(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    moment: datetime,
    erp_company_id: int | None,
    crm_client_id: int | None,
    erp_deal_id: int,
    deal_number: str,
    title: str,
    erp_request_id: int | None,
    summary: str | None,
    parties: RequestParties | None = None,
) -> Letter:
    """Письмо по заявке ERP (`erp.request.created`, EDS-01). Идемпотентно: повтор — то же письмо, без второго номера.

    Отправитель (компания, ИНН, контакт) и менеджер — из `parties` (C1-G-7); их нет — письмо без них, как раньше.
    """
    if erp_request_id is not None:
        existing = await find_by_request(session, erp_request_id)
    else:
        stmt = select(Letter).where(Letter.erp_deal_id == erp_deal_id, Letter.erp_request_id.is_(None))
        existing = (await session.execute(stmt.order_by(Letter.registered_at).limit(1))).scalar_one_or_none()
    if existing is not None:
        log.info("letter_for_request_exists", number=existing.number)
        return existing
    subject = (title.strip() or f"Заявка {deal_number}")[:300]
    values = {
        "subject": subject,
        "summary": (summary or "").strip() or subject,
        "received_at": clock.company_date(moment),
        "erp_request_id": erp_request_id,
        "erp_deal_id": erp_deal_id,
        "deal_number": deal_number[:64],
        "crm_client_id": crm_client_id,
        "erp_company_id": erp_company_id,
        **(parties or RequestParties()).values(),
    }
    return await _insert(session, bus, actor_id=None, values=values, file_ids=[])


async def resolve(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, letter_id: uuid.UUID, data: ResolutionIn
) -> Letter:
    """Резолюция директора: исполнители, срок, мин. маржа → `resolved` и `letter.resolved` (ERP создаёт задание)."""
    letter = await get_for_update(session, letter_id)
    _require(letter, LetterStatus.AWAITING_RESOLUTION)
    if data.due < clock.company_date(clock.now()):  # C1-G-1: срок в прошлом сразу делает КП опоздавшим
        raise invalid_fields("Срок расчёта не может быть в прошлом.", due="due_in_past")
    pairs = [(a.crm_user_id, a.zone.value) for a in data.assignees]
    if len(set(pairs)) != len(pairs):
        raise invalid_fields("Исполнитель указан дважды в одной зоне.", assignees="duplicate")
    inactive = {uid for uid, _ in pairs} - await active_ids(session, (uid for uid, _ in pairs))
    if inactive:
        raise invalid_fields("Исполнитель не найден или отключён.", assignees="not_active_employee")
    now = clock.now()
    letter.status = LetterStatus.RESOLVED.value
    letter.resolution_text = data.text
    letter.resolution_assignees = [{"crm_user_id": uid, "zone": zone} for uid, zone in pairs]
    letter.resolution_due = data.due
    letter.resolution_min_margin_pct = Decimal(data.min_margin_pct) if data.min_margin_pct is not None else None
    letter.resolution_decided_by, letter.resolution_decided_at, letter.updated_at = actor_id, now, now
    await journal.record(session, "letter.resolved", by=actor_id, letter_id=letter.id, comment=data.text)
    directory = await load_directory(session, [actor_id])
    resolution = {
        "text": data.text,
        "assignees": letter.resolution_assignees,
        "due": data.due.isoformat(),
        "min_margin_pct": fmt_pct(letter.resolution_min_margin_pct),
        "decided_by": directory.person(actor_id).model_dump(),
        "decided_at": now.isoformat(),
    }
    payload = {
        "letter": _ref(letter),
        "links": _links(letter),
        "resolution": resolution,
        "actor": events.actor(actor_id),
    }
    await events.publish(bus, session, "letter.resolved", payload, subject=letter.number)
    return letter


async def return_letter(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, letter_id: uuid.UUID, comment: str
) -> Letter:
    """Вернуть регистратору с комментарием: `returned`, `letter.returned`."""
    letter = await get_for_update(session, letter_id)
    _require(letter, LetterStatus.AWAITING_RESOLUTION)
    letter.status, letter.return_comment, letter.updated_at = LetterStatus.RETURNED.value, comment, clock.now()
    await journal.record(session, "letter.returned", by=actor_id, letter_id=letter.id, comment=comment)
    payload = {"letter": _ref(letter), "links": _links(letter), "comment": comment, "actor": events.actor(actor_id)}
    await events.publish(bus, session, "letter.returned", payload, subject=letter.number)
    return letter


async def reject(session: AsyncSession, bus: AsyncBus, *, actor_id: int, letter_id: uuid.UUID, reason: str) -> Letter:
    """Отклонить с причиной: `rejected`, `letter.rejected` (ERP переводит сделку в `LOST`)."""
    letter = await get_for_update(session, letter_id)
    _require(letter, LetterStatus.AWAITING_RESOLUTION)
    letter.status, letter.reject_reason, letter.updated_at = LetterStatus.REJECTED.value, reason, clock.now()
    await journal.record(session, "letter.rejected", by=actor_id, letter_id=letter.id, comment=reason)
    payload = {"letter": _ref(letter), "links": _links(letter), "reason": reason, "actor": events.actor(actor_id)}
    await events.publish(bus, session, "letter.rejected", payload, subject=letter.number)
    return letter


async def _check_request_link(session: AsyncSession, letter: Letter, links: ErpLinksIn) -> None:
    """Правка ссылки на заявку не должна занять заявку другого письма."""
    request_id = links.erp_request_id
    if "erp_request_id" not in links.model_fields_set or request_id in (None, letter.erp_request_id):
        return
    if await find_by_request(session, request_id) is not None:
        raise conflict("letter_exists_for_request", "Письмо по этой заявке уже зарегистрировано.")


async def resubmit(
    session: AsyncSession, *, actor_id: int, letter_id: uuid.UUID, data: LetterSubmitIn | None
) -> Letter:
    """Повторная подача возвращённого письма: правки, `awaiting_resolution`, номер прежний, событие не публикуется."""
    letter = await get_for_update(session, letter_id)
    _require(letter, LetterStatus.RETURNED)
    edits = data or LetterSubmitIn()
    if edits.subject is not None:
        letter.subject = edits.subject
    if edits.summary is not None:
        letter.summary = edits.summary
    if edits.links is not None:
        await _check_request_link(session, letter, edits.links)
        for name in edits.links.model_fields_set:
            setattr(letter, name, getattr(edits.links, name))
    if edits.file_ids:
        await files.attach(session, edits.file_ids, actor_id=actor_id, letter_id=letter.id)
    letter.status, letter.return_comment, letter.updated_at = LetterStatus.AWAITING_RESOLUTION.value, None, clock.now()
    await journal.record(session, "letter.resubmitted", by=actor_id, letter_id=letter.id, comment=edits.comment)
    return letter
