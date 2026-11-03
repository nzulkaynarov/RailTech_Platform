"""Одно письмо — один входящий номер (EDS-DUP; ГОСТ Р 7.0.97: документ регистрируется один раз).

Эталоны: 1С:Документооборот — проверка дублей входящего по «Корреспондент + Исходящий номер + Дата» с окном «Найдены
похожие документы»; Directum RX — поиск дублей при регистрации.

- **Точное совпадение** — тот же корреспондент (ИНН у обоих — по ИНН; иначе тот же клиент CRM или то же название без
  регистра, кавычек, формы собственности и лишних пробелов), тот же исходящий номер (без регистра, пробелов и «№») и
  та же дата исходящего. Регистрация без `force` — 409 `duplicate_letter`; гонку двух регистраций ловит уникальный
  индекс `uq_letters_dedup_key` по `exact_key`.
- **Похожее** — тот же корреспондент и тема за ±3 дня, тот же исх. № с другой датой, тот же файл (SHA-256): только
  предупреждение формы (`POST /letters/duplicates-check`).
- **«Это дубль ВХ-…»** — закрыть уже зарегистрированный дубль (`mark_duplicate`).
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import EdsError, conflict, invalid_fields, not_found
from app.models import Acquaintance, FileVersion, Instruction, InstructionExtension, Letter, StoredFile
from app.schemas.letters import (
    DuplicateMatch,
    LetterDuplicate,
    LetterDuplicateCheck,
    LetterDuplicateCheckIn,
    LetterMarkDuplicateIn,
    LetterStatus,
    LetterTrack,
)
from app.services import journal
from app.services.instructions import IN_WORK, track_of

# Формы собственности — отдельными словами (рус., лат., узб.); «000» — частая опечатка «ООО».
LEGAL_FORMS = frozenset(
    {
        "ооо",
        "ooo",
        "000",
        "llc",
        "mchj",
        "мчж",
        "ао",
        "ao",
        "оао",
        "зао",
        "пао",
        "ип",
        "ltd",
        "jsc",
        "inc",
        "aj",
        "аж",
        "хк",
        "xk",
        "чп",
    }
)
_PUNCT = re.compile(r"[«»\"“”„‟'`’‘.,;:()\[\]{}]")
SIMILAR_DAYS = 3
LIMIT = 5
CANCELLED = "cancelled"
DUPLICATE = LetterStatus.DUPLICATE.value
_OPEN = (LetterStatus.AWAITING_RESOLUTION.value, LetterStatus.RETURNED.value)


def _text(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().replace("ё", "е")


def name_key(name: str | None) -> str:
    """Название корреспондента для сравнения: регистр, кавычки «»"", ООО/OOO/LLC/MChJ, лишние пробелы."""
    return " ".join(word for word in _PUNCT.sub(" ", _text(name)).split() if word not in LEGAL_FORMS)


def ref_key(ref: str | None) -> str:
    """Исходящий номер отправителя: без регистра, пробелов, «№» и «#»."""
    return re.sub(r"\s", "", _text(re.sub(r"[№#]", "", ref or "")))  # «№» до NFKC: иначе он станет «No»


def subject_key(subject: str | None) -> str:
    return " ".join(_PUNCT.sub(" ", _text(subject)).split())


def exact_key(
    inn: str | None, name: str | None, client: int | None, ref: str | None, ref_date: date | None
) -> str | None:
    """Ключ точного совпадения для уникального индекса; без номера, даты или корреспондента — `None`."""
    number = ref_key(ref)
    if not number or ref_date is None:
        return None
    if inn:
        sender = f"i:{inn}"
    elif name_key(name):
        sender = f"n:{name_key(name)}"
    elif client is not None:
        sender = f"c:{client}"
    else:
        return None
    return f"{number}|{ref_date.isoformat()}|{sender}"[:400]


@dataclass(frozen=True)
class Probe:
    """Что проверяем: поля формы регистрации."""

    name: str | None = None
    inn: str | None = None
    client: int | None = None
    ref: str | None = None
    ref_date: date | None = None
    subject: str | None = None
    received_at: date | None = None
    file_ids: list[uuid.UUID] = field(default_factory=list)

    @classmethod
    def of(cls, data: LetterDuplicateCheckIn) -> "Probe":
        sender, ref = data.sender, data.sender_ref
        return cls(
            name=sender.name if sender else None,
            inn=sender.inn if sender else None,
            client=data.crm_client_id,
            ref=ref.number if ref else None,
            ref_date=ref.date if ref else None,
            subject=data.subject,
            received_at=data.received_at,
            file_ids=list(data.file_ids),
        )

    @property
    def key(self) -> str | None:
        return exact_key(self.inn, self.name, self.client, self.ref, self.ref_date)


def same_sender(probe: Probe, letter: Letter) -> bool:
    if probe.inn and letter.sender_inn:
        return probe.inn == letter.sender_inn
    if probe.client is not None and probe.client == letter.crm_client_id:
        return True
    name = name_key(probe.name)
    return bool(name) and name == name_key(letter.sender_name)


def _digits(ref: str | None) -> str:
    return re.sub(r"\D", "", ref or "")


def _same_ref_clause(probe: Probe) -> Any:
    """Отбор кандидатов по номеру без зависимости от локали базы: те же цифры; сравнение целиком — в Python."""
    digits = _digits(probe.ref)
    column = Letter.sender_ref_number
    if digits:
        return func.regexp_replace(column, r"\D", "", "g") == digits
    return column.is_not(None)


async def find_exact(session: AsyncSession, probe: Probe) -> Letter | None:
    """Самое раннее зарегистрированное то же письмо (не дубль); нет ключа — `None`."""
    if probe.key is None:
        return None
    stmt = (
        select(Letter)
        .where(Letter.sender_ref_date == probe.ref_date, Letter.status != DUPLICATE, _same_ref_clause(probe))
        .order_by(Letter.registered_at, Letter.id)
    )
    ref = ref_key(probe.ref)
    for letter in (await session.execute(stmt)).scalars():
        if ref_key(letter.sender_ref_number) == ref and same_sender(probe, letter):
            return letter
    return None


def as_item(letter: Letter, match: DuplicateMatch | None = None) -> LetterDuplicate:
    return LetterDuplicate(
        id=letter.id,
        number=letter.number,
        subject=letter.subject,
        received_at=letter.received_at,
        status=LetterStatus(letter.status),
        registered_at=letter.registered_at,
        match=match,
    )


def duplicate_error(letter: Letter) -> EdsError:
    return conflict(
        "duplicate_letter",
        f"Это письмо уже зарегистрировано: {letter.number}.",
        duplicate=as_item(letter, DuplicateMatch.EXACT).model_dump(mode="json"),
    )


async def _by_files(session: AsyncSession, probe: Probe, actor_id: int) -> list[Letter]:
    if not probe.file_ids:
        return []
    own = select(FileVersion.sha256).join(StoredFile, StoredFile.id == FileVersion.file_id)
    hashes = own.where(StoredFile.id.in_(probe.file_ids), StoredFile.created_by == actor_id)
    stmt = (
        select(Letter)
        .join(StoredFile, StoredFile.letter_id == Letter.id)
        .join(FileVersion, FileVersion.file_id == StoredFile.id)
        .where(FileVersion.sha256.in_(hashes), Letter.status != DUPLICATE)
        .order_by(Letter.registered_at.desc())
        .limit(LIMIT)
    )
    return list((await session.execute(stmt)).scalars().unique())


async def check(session: AsyncSession, probe: Probe, *, actor_id: int) -> LetterDuplicateCheck:
    """Точное совпадение первым, затем похожие; одно письмо — один раз, не больше пяти."""
    found: dict[uuid.UUID, LetterDuplicate] = {}
    exact = await find_exact(session, probe)
    if exact is not None:
        found[exact.id] = as_item(exact, DuplicateMatch.EXACT)
    near: list[Any] = []
    if probe.ref and ref_key(probe.ref):
        near.append(_same_ref_clause(probe))
    if probe.received_at is not None and subject_key(probe.subject):
        window = timedelta(days=SIMILAR_DAYS)
        near.append(Letter.received_at.between(probe.received_at - window, probe.received_at + window))
    if near:
        stmt = select(Letter).where(Letter.status != DUPLICATE, or_(*near)).order_by(Letter.registered_at.desc())
        subject, ref = subject_key(probe.subject), ref_key(probe.ref)
        for letter in (await session.execute(stmt.limit(200))).scalars():
            if letter.id in found or not same_sender(probe, letter):
                continue
            if ref and ref_key(letter.sender_ref_number) == ref:
                found[letter.id] = as_item(letter, DuplicateMatch.SAME_REF)
            elif (
                subject
                and subject_key(letter.subject) == subject
                and probe.received_at is not None
                and abs((letter.received_at - probe.received_at).days) <= SIMILAR_DAYS
            ):
                found[letter.id] = as_item(letter, DuplicateMatch.SAME_SUBJECT)
    for letter in await _by_files(session, probe, actor_id):
        found.setdefault(letter.id, as_item(letter, DuplicateMatch.SAME_FILE))
    return LetterDuplicateCheck(items=list(found.values())[:LIMIT])


# --- «Это дубль ВХ-…» ---------------------------------------------------------------------------------------------


async def _lock_pair(session: AsyncSession, letter_id: uuid.UUID, number: str) -> tuple[Letter, Letter | None]:
    """Письмо и оригинал под блокировкой в порядке id (две встречные пометки не дают взаимной блокировки)."""
    original_id = (await session.execute(select(Letter.id).where(Letter.number == number))).scalar_one_or_none()
    ids = [letter_id] if original_id is None else [letter_id, original_id]
    rows = {
        r.id: r
        for r in (
            await session.execute(select(Letter).where(Letter.id.in_(ids)).order_by(Letter.id).with_for_update())
        ).scalars()
    }
    if letter_id not in rows:
        raise not_found("Письмо не найдено.")
    return rows[letter_id], rows.get(original_id) if original_id is not None else None


async def _cancel_work(session: AsyncSession, letter: Letter, actor_id: int, why: str) -> tuple[int, int]:
    """Поручения в работе — «Отменено», их запросы переноса — отклонены; ожидающие «ознакомить» снимаются."""
    now = clock.now()
    work = list(
        (
            await session.execute(
                select(Instruction)
                .where(Instruction.letter_id == letter.id, Instruction.status == IN_WORK)
                .with_for_update()
            )
        ).scalars()
    )
    for row in work:
        row.status, row.updated_at = CANCELLED, now
    if work:
        pending = await session.execute(
            select(InstructionExtension)
            .where(
                InstructionExtension.instruction_id.in_([r.id for r in work]), InstructionExtension.status == "pending"
            )
            .with_for_update()
        )
        for ext in pending.scalars():
            ext.status, ext.decided_by, ext.decided_at, ext.comment = "rejected", actor_id, now, why
    gone = await session.execute(
        delete(Acquaintance)
        .where(Acquaintance.letter_id == letter.id, Acquaintance.acknowledged_at.is_(None))
        .returning(Acquaintance.id)
    )
    return len(work), len(gone.all())


async def mark_duplicate(
    session: AsyncSession, *, actor_id: int, letter_id: uuid.UUID, data: LetterMarkDuplicateIn
) -> Letter:
    """Закрыть письмо как дубль оригинала: статус `duplicate`, номер не освобождается, работа по письму отменяется."""
    number = data.original_number.strip()
    letter, original = await _lock_pair(session, letter_id, number)
    if letter.status == DUPLICATE:
        raise conflict("invalid_state", "Письмо уже отмечено как дубль.", status=letter.status)
    if original is None:
        raise invalid_fields("Входящего с таким номером нет.", original_number="not_found")
    if original.id == letter.id:
        raise invalid_fields("Это то же письмо.", original_number="same_letter")
    if original.status == DUPLICATE:
        raise invalid_fields("Это письмо само дубль — укажите оригинал.", original_number="original_is_duplicate")
    resolved = letter.status not in _OPEN
    if resolved and track_of(letter) is LetterTrack.CALC:
        raise conflict("calc_in_progress", "По письму уже идёт расчёт: закройте его в проекте.", status=letter.status)
    in_work = (
        await session.execute(
            select(func.count()).where(Instruction.letter_id == letter.id, Instruction.status == IN_WORK)
        )
    ).scalar_one()
    if resolved and not data.confirm:
        raise conflict(
            "resolution_exists",
            "По письму уже наложена резолюция: подтвердите отмену поручений.",
            status=letter.status,
            instructions=in_work,
        )
    why = f"Письмо — дубль {original.number}."
    cancelled, unacquainted = await _cancel_work(session, letter, actor_id, why)
    key = letter.dedup_key
    letter.status, letter.on_control, letter.duplicate_of_id = DUPLICATE, False, original.id
    letter.dedup_key, letter.updated_at = None, clock.now()
    await session.flush()
    if original.dedup_key is None and key is not None:  # ключ переходит к оригиналу: новые дубли ловит индекс
        original.dedup_key = key
    comment = (data.comment or "").strip()
    await journal.record(
        session,
        "letter.marked_duplicate",
        by=actor_id,
        letter_id=letter.id,
        comment=f"Дубль {original.number}" + (f": {comment}" if comment else ""),
    )
    if cancelled or unacquainted:
        await journal.record(
            session,
            "letter.work_cancelled",
            by=actor_id,
            letter_id=letter.id,
            comment=f"Отменено поручений: {cancelled}, ознакомлений: {unacquainted}. {why}",
        )
    await journal.record(
        session, "letter.duplicate_linked", by=actor_id, letter_id=original.id, comment=f"Дубль: {letter.number}"
    )
    return letter
