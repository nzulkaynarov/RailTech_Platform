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
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import EdsError, conflict, invalid_fields, not_found
from app.models import Document, Letter
from app.schemas.common import ErpLinksIn
from app.schemas.letters import (
    LetterCreate,
    LetterDuplicate,
    LetterDuplicateList,
    LetterStatus,
    LetterSubmitIn,
    LetterTrack,
    ResolutionIn,
)
from app.services import dictionaries, events, files, instructions, journal, letter_dedup, numbering
from app.services.people import active_ids, default_director, load_directory, zone_mismatches

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


async def _publish_registered(
    bus: AsyncBus,
    session: AsyncSession,
    letter: Letter,
    actor_id: int | None,
    source: dict[str, Any] | None = None,
) -> None:
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
    if source is not None:  # W18A-P2: письмо общего ящика CRM — CRM снимает его с очереди
        data["source"] = source
    await events.publish(bus, session, "letter.registered", data, subject=letter.number)


async def _insert(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    actor_id: int | None,
    values: dict[str, Any],
    file_ids: list[uuid.UUID],
    source: dict[str, Any] | None = None,
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
    await _publish_registered(bus, session, letter, actor_id, source)
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


async def _related(session: AsyncSession, number: str | None) -> dict[str, uuid.UUID | None]:
    """Связь с предыдущим ВХ или нашим ИСХ по номеру (P8); номера нет в реестре — 422 `related_number`."""
    if number is None:
        return {"related_letter_id": None, "related_document_id": None}
    letter_id = (await session.execute(select(Letter.id).where(Letter.number == number))).scalar_one_or_none()
    if letter_id is not None:
        return {"related_letter_id": letter_id, "related_document_id": None}
    stmt = select(Document.id).where(Document.number == number, Document.kind == "letter_out")
    document_id = (await session.execute(stmt)).scalar_one_or_none()
    if document_id is None:
        raise invalid_fields("Документ с таким номером не найден.", related_number="not_found")
    return {"related_letter_id": None, "related_document_id": document_id}


def _sender_key(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


async def find_duplicates(
    session: AsyncSession, *, sender_name: str | None, crm_client_id: int | None, ref_number: str
) -> LetterDuplicateList:
    """Проверка дубля перед регистрацией (P8, SPEC-v3 §3.2a п. 1): тот же исх. № отправителя и тот же корреспондент —
    по названию без учёта регистра и лишних пробелов или по клиенту CRM. Предупреждение, не запрет."""
    ref = ref_number.strip()
    name = _sender_key(sender_name)
    if not ref or (not name and crm_client_id is None):
        return LetterDuplicateList(items=[])
    same_sender = []
    if name:
        same_sender.append(func.lower(func.regexp_replace(func.trim(Letter.sender_name), r"\s+", " ", "g")) == name)
    if crm_client_id is not None:
        same_sender.append(Letter.crm_client_id == crm_client_id)
    stmt = (
        select(Letter)
        .where(func.trim(Letter.sender_ref_number) == ref, or_(*same_sender))
        .order_by(Letter.registered_at.desc())
        .limit(5)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return LetterDuplicateList(
        items=[
            LetterDuplicate(
                id=r.id, number=r.number, subject=r.subject, received_at=r.received_at, status=LetterStatus(r.status)
            )
            for r in rows
        ]
    )


async def register(session: AsyncSession, bus: AsyncBus, *, actor_id: int, data: LetterCreate) -> Letter:
    """Ручная регистрация (`POST /letters`). Нужен отправитель по имени или клиент CRM в `links`.

    Карточка делопроизводства (P8): вид документа и способ получения — действующие коды справочников (EDS-REG); вид
    со «срочно» (требование ГНК) ставит «срочно» сам; связь с предыдущим ВХ или нашим ИСХ — по номеру.
    """
    links = data.links or ErpLinksIn()
    if not data.sender.name and links.crm_client_id is None:
        raise invalid_fields("Укажите отправителя или клиента.", sender="name_or_client_required")
    kind = await dictionaries.find(session, dictionaries.LETTER_KINDS, data.kind) if data.kind is not None else None
    if data.kind is not None and kind is None:
        raise invalid_fields("Такого вида документа нет в справочнике.", kind="unknown_kind")
    if data.receipt_method is not None and (
        await dictionaries.find(session, dictionaries.RECEIPT_METHODS, data.receipt_method) is None
    ):
        raise invalid_fields("Такого способа получения нет в справочнике.", receipt_method="unknown_method")
    if links.erp_request_id is not None and await find_by_request(session, links.erp_request_id) is not None:
        raise conflict("letter_exists_for_request", "Письмо по этой заявке уже зарегистрировано.")
    await _validate_staff(
        session, addressee_crm_user_id=data.addressee_crm_user_id, manager_crm_user_id=data.manager_crm_user_id
    )
    ref = data.sender_ref
    values: dict[str, Any] = {
        "subject": data.subject,
        "summary": (data.summary or "").strip() or data.subject,
        "sender_name": data.sender.name,
        "sender_inn": data.sender.inn,
        "sender_contact": data.sender.contact,
        "sender_ref_number": ref.number if ref else None,
        "sender_ref_date": ref.date if ref else None,
        "received_at": data.received_at,
        "addressee_crm_user_id": data.addressee_crm_user_id,
        "manager_crm_user_id": data.manager_crm_user_id,
        "urgent": data.urgent or (kind is not None and kind.attrs.get("urgent") is True),
        "doc_kind": data.kind,
        "receipt_method": data.receipt_method,
        "signed_by": (data.signed_by or "").strip() or None,
        "document_due": data.document_due,
        **await _related(session, data.related_number),
        **_link_values(data.links),
    }
    if data.resolution_draft is not None and data.resolution_draft.kind is not None:
        # Проект резолюции делопроизводителя (P8b) — только у письма пути делопроизводства.
        probe = Letter(doc_kind=data.kind, erp_request_id=links.erp_request_id, erp_deal_id=links.erp_deal_id)
        if instructions.track_of(probe) is not LetterTrack.OFFICE:
            raise conflict("track_mismatch", "Проект резолюции — только у письма делопроизводства.")
        values["resolution_draft"] = instructions.stamp_draft(
            await instructions.validate_draft(session, data.resolution_draft), actor_id
        )
    same = letter_dedup.Probe(
        name=data.sender.name,
        inn=data.sender.inn,
        client=links.crm_client_id,
        ref=ref.number if ref else None,
        ref_date=ref.date if ref else None,
    )
    forced = await _check_duplicate(session, same, data)
    values["dedup_key"] = None if forced is not None else same.key
    try:
        source = data.source.model_dump() if data.source is not None else None
        if data.source is not None:
            values["source_mail_id"] = data.source.crm_inbound_mail_id
        async with session.begin_nested():
            letter = await _insert(
                session, bus, actor_id=actor_id, values=values, file_ids=data.file_ids, source=source
            )
    except IntegrityError as exc:
        if "uq_letters_source_mail_id" in str(exc.orig):  # гонка двух регистраций одного письма ящика
            raise SourceMailTakenError from exc
        if "uq_letters_dedup_key" in str(exc.orig):  # EDS-DUP: то же письмо только что зарегистрировал другой
            winner = await letter_dedup.find_exact(session, same)
            if winner is not None:
                raise letter_dedup.duplicate_error(winner) from exc
            raise conflict("letter_source_busy", "Письмо уже регистрируется: повторите запрос.") from exc
        # гонка с обработчиком `request.created`: заявку уже заняло другое письмо
        raise conflict("letter_exists_for_request", "Письмо по этой заявке уже зарегистрировано.") from exc
    if forced is not None:
        reason = (data.force_reason or "").strip()
        comment = f"Совпадает с {forced.number}: {reason}"
        await journal.record(session, "letter.duplicate_forced", by=actor_id, letter_id=letter.id, comment=comment)
    return letter


async def _check_duplicate(session: AsyncSession, probe: letter_dedup.Probe, data: LetterCreate) -> Letter | None:
    """EDS-DUP: то же письмо уже есть — 409 `duplicate_letter`; с `force` и причиной — найденный ВХ (в журнал)."""
    if data.force and not (data.force_reason or "").strip():
        raise invalid_fields("Укажите, почему это другое письмо.", force_reason="required")
    found = await letter_dedup.find_exact(session, probe)
    if found is not None and not data.force:
        raise letter_dedup.duplicate_error(found)
    return found


class SourceMailTakenError(Exception):
    """Письмо общего ящика уже имеет ВХ (сработал `uq_letters_source_mail_id`)."""


async def find_by_source(session: AsyncSession, crm_inbound_mail_id: int) -> Letter | None:
    stmt = select(Letter).where(Letter.source_mail_id == crm_inbound_mail_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def register_once(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, data: LetterCreate
) -> tuple[Letter, bool]:
    """Регистрация, у которой письмо общего ящика (`source`) получает ВХ один раз (W18A-P2-3): повтор — тот же ВХ
    без нового номера и без второго `letter.registered`; `False` во втором элементе — «уже был». Две одновременные
    регистрации ловит уникальный индекс: проигравшая откатывается до точки сохранения и читает ВХ победившей."""
    if data.source is None:
        return await register(session, bus, actor_id=actor_id, data=data), True
    mail_id = data.source.crm_inbound_mail_id
    if (found := await find_by_source(session, mail_id)) is not None:
        return found, False
    try:
        async with session.begin_nested():
            return await register(session, bus, actor_id=actor_id, data=data), True
    except SourceMailTakenError:
        found = await find_by_source(session, mail_id)
        if found is None:  # победительница откатилась между вставкой и чтением — пусть клиент повторит
            raise conflict("letter_source_busy", "Письмо уже регистрируется: повторите запрос.") from None
        return found, False


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
    urgent: bool = False,
    letter_file_id: uuid.UUID | None = None,
) -> Letter:
    """Письмо по заявке ERP (`erp.request.created`, EDS-01). Идемпотентно: повтор — то же письмо, без второго номера.

    Отправитель (компания, ИНН, контакт) и менеджер — из `parties` (C1-G-7); их нет — письмо без них, как раньше.
    «Создать заявку» (W16-D1-2): срочность — `urgent`; файл письма директору `letter_file_id` привязывается к письму,
    если его загрузил менеджер заявки и он ещё ни к чему не привязан; иначе письмо регистрируется без файла (в журнал —
    `letter_file_not_attached`), событие не повторяется. Старое событие без этих полей — письмо как раньше.
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
        "urgent": urgent,
        **(parties or RequestParties()).values(),
    }
    letter = await _insert(session, bus, actor_id=None, values=values, file_ids=[])
    if letter_file_id is not None:
        await _attach_request_file(session, letter, letter_file_id)
    return letter


async def _attach_request_file(session: AsyncSession, letter: Letter, file_id: uuid.UUID) -> None:
    """Файл письма по заявке — от имени загрузившего его менеджера заявки; чужой или занятый файл не прикрепляется."""
    manager = letter.manager_crm_user_id
    if manager is None:
        log.warning("letter_file_not_attached", number=letter.number, file_id=str(file_id), reason="no_manager")
        return
    try:
        async with session.begin_nested():
            await files.attach(session, [file_id], actor_id=manager, letter_id=letter.id)
    except EdsError as exc:
        log.warning("letter_file_not_attached", number=letter.number, file_id=str(file_id), reason=exc.body.code)


async def resolve(
    session: AsyncSession, bus: AsyncBus, *, actor_id: int, letter_id: uuid.UUID, data: ResolutionIn
) -> Letter:
    """Резолюция директора: исполнители, срок, мин. маржа → `resolved` и `letter.resolved` (ERP создаёт задание)."""
    letter = await get_for_update(session, letter_id)
    _require(letter, LetterStatus.AWAITING_RESOLUTION)
    if instructions.track_of(letter) is not LetterTrack.CALC:  # P8b: делопроизводство — резолюция трёх типов
        raise conflict(
            "track_mismatch",
            "Письмо не по заявке клиента: резолюция — К исполнению, Подготовить ответ или Для сведения.",
        )
    if data.due < clock.company_date(clock.now()):  # C1-G-1: срок в прошлом сразу делает КП опоздавшим
        raise invalid_fields("Срок расчёта не может быть в прошлом.", due="due_in_past")
    pairs = [(a.crm_user_id, a.zone.value) for a in data.assignees]
    if len(set(pairs)) != len(pairs):
        raise invalid_fields("Исполнитель указан дважды в одной зоне.", assignees="duplicate")
    inactive = {uid for uid, _ in pairs} - await active_ids(session, (uid for uid, _ in pairs))
    if inactive:
        raise invalid_fields("Исполнитель не найден или отключён.", assignees="not_active_employee")
    if await zone_mismatches(session, pairs):  # B-007: исполнитель зоны имеет раздел зоны (проекция из identity)
        raise invalid_fields("У исполнителя нет раздела выбранной зоны.", assignees="assignee_zone_mismatch")
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
    if instructions.track_of(letter) is LetterTrack.OFFICE:
        return letter  # P8b: отказ по письму делопроизводства сделку не закрывает — `letter.rejected` только для заявок
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
