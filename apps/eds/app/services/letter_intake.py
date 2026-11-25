"""«Заполнить из файла» — ИИ-помощник регистрации входящего (EDS-REG; стандарт ИИ-помощника — исследование
`docs/research/2026-11-02-flexibility/5-ai-assist.md` §4; правила юриста — DECISIONS 2026-11-02).

* Только по кнопке: сервис вызывается из `POST /letter-intake`, ничего не пишет в письмо — предлагает поля.
* PDF с текстовым слоем: текст извлекает EDS (`pypdf`), персональные данные маскирует код (`security/pii.py`) по
  политике защиты данных для ИИ (PD-BIZ, DECISIONS 2026-11-03; «Деловая» по умолчанию — паспорт, ПИНФЛ, карты,
  даты рождения; «Строгая» — ещё телефоны, почта, ИНН, счета). В модель уходит только маскированный текст;
  метки `[number_N]` в ответе код возвращает локально. Политику каждый вызов читает из `docflow_settings`:
  смена в CRM действует сразу.
* Скан или фото без текста — модель с изображением: при «Деловой» и включённой настройке `recognize_scans` (по умолчанию
  включена, переключатель — «Расходы на ИИ» Платформы, подпись «паспорта и личные документы не загружайте»); при
  «Строгой» — отказ `scan_recognition_disabled` (409), как и при выключенной настройке.
* Пределы проверяются до чтения файла: PDF — 10 МБ и 30 страниц, изображение — 5 МБ; разбор PDF — в потоке.
* Код решает: вид документа — только действующий код справочника, даты — разбираются и проверяются, ИНН корреспондента
  ищет код в исходном тексте (не модель).
* Журнал `ai_suggestions`: кто, когда, функция, алиас, версия промпта, источник, итог, токены, стоимость — без текстов;
  решение человека — `decide`.
"""

import asyncio
import base64
import io
import re
import uuid
from datetime import UTC, date, timedelta
from decimal import Decimal
from typing import Any, Final

import structlog
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.ai import gateway
from app.config import Settings
from app.errors import conflict, invalid_fields, not_found
from app.models import AiSuggestion, Employee, Letterhead
from app.schemas.ai import AiDecision, IntakeSource, LetterIntakeFields, LetterIntakeSuggestion
from app.security.pii import Masked, mask_numbered
from app.services import dictionaries, docflow_settings, files
from app.services.storage import ObjectStorage

log = structlog.get_logger(__name__)

FUNCTION: Final = "letter_intake"
RULES_ALIAS: Final = "rules"  # предложение по правилам кода, без модели (СЦ-11)
RULES_VERSION: Final = "rules-1"
PDF: Final = "application/pdf"
IMAGES: Final = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
MIN_TEXT = 40  # меньше знаков в текстовом слое — считаем сканом
MAX_TEXT = 12_000  # первые страницы письма: суть, реквизиты, срок
MAX_PAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # предел изображения у провайдеров моделей
MAX_PDF_BYTES = 10 * 1024 * 1024  # письмо — страницы текста; больше — не письмо, а пакет документов
MAX_PDF_PAGES = 30
DUE_PAST = timedelta(days=365)  # срок по документу: не старше года и не дальше двух лет — иначе ошибка распознавания
DUE_AHEAD = timedelta(days=730)
MAX_TOKENS = 1200
# ИНН организации РУз — 9 цифр рядом со словом ИНН/STIR/INN/TIN; 14 цифр (ПИНФЛ) — личные данные, их не берём.
_INN: Final = re.compile(r"(?i)(?:\bИНН|\bSTIR|\bINN|\bTIN)\b\D{0,12}?(\d{9})(?!\d)")

# «в течение 5 рабочих дней», «в течение десяти календарных дней», «5 kun ichida», «5 ish kuni ichida».
_NUM_WORDS: Final[dict[str, int]] = {
    # именительный и родительный падеж числительных 1–30 («в течение пяти дней», «тридцати календарных дней»)
    **{
        w: n
        for n, ws in enumerate(
            (
                "один одного одну",
                "два двух",
                "три трёх трех",
                "четыре четырёх четырех",
                "пять пяти",
                "шесть шести",
                "семь семи",
                "восемь восьми",
                "девять девяти",
                "десять десяти",
                "одиннадцать одиннадцати",
                "двенадцать двенадцати",
                "тринадцать тринадцати",
                "четырнадцать четырнадцати",
                "пятнадцать пятнадцати",
                "шестнадцать шестнадцати",
                "семнадцать семнадцати",
                "восемнадцать восемнадцати",
                "девятнадцать девятнадцати",
                "двадцать двадцати",
            ),
            start=1,
        )
        for w in ws.split()
    },
    "тридцать": 30,
    "тридцати": 30,
}
_WORDS_RE = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))
_DUE_RU: Final = re.compile(
    rf"(?i)в\s+течение\s+(?:(\d{{1,3}})|({_WORDS_RE}))\s*(?:\([^)]{{1,30}}\)\s*)?(рабоч\w*|календарн\w*)?\s*дн"
)
_DUE_UZ: Final = re.compile(r"(?i)\b(\d{1,3})\s*(ish\s+)?kun(?:i)?\s+ichida")
_MAX_DUE_DAYS = 90

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sender_name",
        "sender_ref_number",
        "sender_ref_date",
        "subject",
        "summary",
        "kind",
        "document_due",
    ],
    "properties": {
        name: {"type": ["string", "null"]}
        for name in (
            "sender_name",
            "sender_ref_number",
            "sender_ref_date",
            "subject",
            "summary",
            "kind",
            "document_due",
        )
    },
}
LIMITS: Final = {"sender_name": 255, "sender_ref_number": 64, "subject": 300, "summary": 2000}


class TooManyPagesError(Exception):
    """PDF длиннее `MAX_PDF_PAGES`: это не письмо, а пакет документов — помощник его не читает."""


def pdf_text(data: bytes) -> str:
    """Текстовый слой первых страниц PDF; битый или зашифрованный файл — пустая строка (дальше — как скан).

    Больше `MAX_PDF_PAGES` страниц — `TooManyPagesError`. Синхронно: вызывать через `asyncio.to_thread`."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise TooManyPagesError
        parts = [(page.extract_text() or "") for page in reader.pages[:MAX_PAGES]]
    except (PyPdfError, ValueError, KeyError, TypeError, OSError):
        return ""
    text = re.sub(r"[ \t]+", " ", "\n".join(parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT]


def find_inn(text: str, own: str | None = None) -> str | None:
    """ИНН отправителя: первый ИНН организации в тексте, кроме ИНН своей компании (реквизиты адресата в письме)."""
    for found in _INN.finditer(text):
        if found.group(1) != own:
            return found.group(1)
    return None


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _text(value: Any, masked: Masked | None, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join((masked.unmask(value) if masked else value).split())
    return cleaned[:limit] or None


def due_from_text(raw: str, today: date) -> date | None:
    """Срок «в течение N (рабочих|календарных) дней» (N цифрами или словом, «пяти дней») из текста письма: код
    считает от даты `today` (даты поступления, а без неё — дня регистрации), а не модель.

    Рабочие дни — пн–пт (как в подсказке срока резолюции); без слова «рабочих» — календарные. Нет оборота или N вне
    разумного — `None`. Это подсказка: срок человек подтверждает в карточке (в письме отсчёт
    может идти от даты поступления)."""
    if not raw:
        return None
    found = _DUE_RU.search(raw)
    working = False
    if found:
        days = int(found.group(1)) if found.group(1) else _NUM_WORDS[found.group(2).lower()]
        working = (found.group(3) or "").lower().startswith("рабоч")
    elif (found := _DUE_UZ.search(raw)) is not None:
        days = int(found.group(1))
        working = bool(found.group(2))
    else:
        return None
    if not 1 <= days <= _MAX_DUE_DAYS:
        return None
    if not working:
        return today + timedelta(days=days)
    day = today
    while days:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day


def clean(
    data: dict[str, Any],
    *,
    masked: Masked | None,
    kinds: set[str],
    raw: str,
    today: date,
    own_inn: str | None = None,
    base: date | None = None,
) -> LetterIntakeFields:
    """Ответ модели → поля карточки: код решает, что принять (вид — из справочника, даты — разобранные и в разумных
    пределах, ИНН — найденный кодом, не свой)."""
    ref_date = _date(data.get("sender_ref_date"))
    due = _date(data.get("document_due")) or due_from_text(raw, base or today)
    kind = data.get("kind")
    return LetterIntakeFields(
        sender_name=_text(data.get("sender_name"), masked, LIMITS["sender_name"]),
        sender_inn=find_inn(raw, own_inn) if raw else None,
        sender_ref_number=_text(data.get("sender_ref_number"), masked, LIMITS["sender_ref_number"]),
        sender_ref_date=ref_date if ref_date and ref_date <= today + timedelta(days=1) else None,
        subject=_text(data.get("subject"), masked, LIMITS["subject"]),
        summary=_text(data.get("summary"), masked, LIMITS["summary"]),
        kind=kind if isinstance(kind, str) and kind in kinds else None,
        document_due=due if due and today - DUE_PAST <= due <= today + DUE_AHEAD else None,
    )


def rules_fields(
    raw: str, today: date, own_inn: str | None = None, base: date | None = None
) -> LetterIntakeFields | None:
    """Поля, которые код берёт из текста письма без модели: срок «в течение N дней» и ИНН отправителя.
    Нет срока в тексте — `None`: одного ИНН для предложения мало."""
    due = due_from_text(raw, base or today)
    if due is None or not today - DUE_PAST <= due <= today + DUE_AHEAD:
        return None
    return LetterIntakeFields(document_due=due, sender_inn=find_inn(raw, own_inn))


async def _rules_suggestion(
    session: AsyncSession, employee: Employee, fields: LetterIntakeFields
) -> LetterIntakeSuggestion:
    """Предложение по правилам кода: в журнале — алиас `rules`, без токенов и стоимости (платного вызова нет)."""
    suggestion_id = uuid.uuid4()
    async with session.begin():
        session.add(
            AiSuggestion(
                id=suggestion_id,
                function=FUNCTION,
                alias=RULES_ALIAS,
                prompt_version=RULES_VERSION,
                source=IntakeSource.TEXT.value,
                status="ok",
                crm_user_id=employee.crm_user_id,
                created_at=clock.now(),
            )
        )
    log.info("ai.letter_intake", suggestion_id=str(suggestion_id), status="ok", source="rules")
    return LetterIntakeSuggestion(
        suggestion_id=suggestion_id,
        source=IntakeSource.TEXT,
        fields=fields,
        alias=RULES_ALIAS,
        prompt_version=RULES_VERSION,
    )


def _kinds_block(items: list[tuple[str, str]]) -> str:
    return "<kinds>\n" + "\n".join(f"{code}: {name}" for code, name in items) + "\n</kinds>"


async def _spent_today(session: AsyncSession) -> Decimal:
    # Сутки UTC — как бюджет ключа в шлюзе.
    start = clock.now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.execute(
        select(func.coalesce(func.sum(AiSuggestion.cost_usd), 0)).where(AiSuggestion.created_at >= start)
    )
    return Decimal(str(total.scalar_one() or 0))


def _too_large(limit: int) -> str:
    return f"Файл больше {limit // (1024 * 1024)} МБ — помощник его не прочитает. Заполните вручную."


async def _read(storage: ObjectStorage, key: str) -> bytes:
    chunks = [chunk async for chunk in storage.stream(key)]
    return b"".join(chunks)


async def suggest(
    session: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    employee: Employee,
    file_id: uuid.UUID,
    received_at: date | None = None,
) -> LetterIntakeSuggestion:
    """Предложить поля карточки по файлу письма. Вызов модели — вне транзакции, журнал — своей транзакцией."""
    async with session.begin():
        await files.load_visible(session, employee, file_id)
        version = await files.get_version(session, file_id, None)
        policy = await docflow_settings.pii_policy(session)
        scans_on = policy == "business" and await docflow_settings.recognize_scans(session)
        spent = await _spent_today(session)
        kinds = [(i.code, i.name.ru) for i in (await dictionaries.list_items(session, dictionaries.LETTER_KINDS)).items]
        own = await session.get(Letterhead, 1)
    own_inn = own.inn if own is not None else None
    if version.content_type != PDF and version.content_type not in IMAGES:
        raise invalid_fields("Заполнить можно из PDF или фото письма.", file_id="unsupported_file")
    # Размер — до чтения файла: большой файл не читаем и не разбираем.
    limit = MAX_PDF_BYTES if version.content_type == PDF else MAX_IMAGE_BYTES
    if version.size > limit:
        raise conflict("file_too_large", _too_large(limit))
    # Модель недоступна или лимит исчерпан — не отказ: правила кода (срок по тексту) работают без модели (СЦ-11).
    blocked: tuple[str, str] | None = None
    budget = Decimal(str(settings.ai_daily_budget_usd))
    if not gateway.available(settings):
        blocked = ("ai_unavailable", "Помощник не настроен — заполните вручную.")
    elif budget > 0 and spent >= budget:  # 0 — без лимита (как у ERP)
        blocked = ("ai_budget_exceeded", "Дневной лимит помощника исчерпан — заполните вручную.")
    data = await _read(storage, version.s3_key)
    try:
        raw = await asyncio.to_thread(pdf_text, data) if version.content_type == PDF else ""
    except TooManyPagesError as exc:
        raise conflict(
            "file_too_large", f"В файле больше {MAX_PDF_PAGES} страниц — это не письмо. Заполните вручную."
        ) from exc
    source = IntakeSource.TEXT if len(raw) >= MIN_TEXT else IntakeSource.IMAGE
    today = clock.company_date(clock.now())
    by_rules = rules_fields(raw, today, own_inn, received_at) if source is IntakeSource.TEXT else None
    if blocked is not None:
        if by_rules is None:
            raise conflict(*blocked)
        return await _rules_suggestion(session, employee, by_rules)
    if source is IntakeSource.IMAGE and not scans_on:
        why = (
            "при строгой политике защиты данных помощник сканы и фото не читает"
            if policy == "strict"
            else "чтение сканов и фото выключено в настройках"
        )
        raise conflict("scan_recognition_disabled", f"Это скан или фото: {why}. Заполните вручную.")
    if source is IntakeSource.IMAGE and len(data) > MAX_IMAGE_BYTES:
        raise conflict("file_too_large", _too_large(MAX_IMAGE_BYTES))

    masked = mask_numbered(raw, policy) if source is IntakeSource.TEXT else None
    if masked is not None:
        letter: dict[str, Any] = {"type": "text", "text": f"<letter>\n{masked.text}\n</letter>"}
    elif version.content_type == PDF:
        encoded = base64.b64encode(data).decode("ascii")
        letter = {"type": "file", "file": {"file_data": f"data:{PDF};base64,{encoded}"}}
    else:
        encoded = base64.b64encode(data).decode("ascii")
        letter = {"type": "image_url", "image_url": {"url": f"data:{version.content_type};base64,{encoded}"}}
    prompt = gateway.load_prompt(FUNCTION)
    suggestion_id = uuid.uuid4()
    body = gateway.body_for(
        function=FUNCTION,
        prompt=prompt,
        user_content=[{"type": "text", "text": _kinds_block(kinds)}, letter],
        schema=SCHEMA,
        max_tokens=MAX_TOKENS,
        user_id=employee.crm_user_id,
        session_id=str(suggestion_id),
    )
    result = await gateway.call_json(settings, body)
    fields = (
        clean(
            result.data,
            masked=masked,
            kinds={c for c, _ in kinds},
            raw=raw,
            today=today,
            own_inn=own_inn,
            base=received_at,
        )
        if result.status == "ok" and result.data is not None
        else None
    )
    empty = fields is not None and not any(fields.model_dump().values())
    status = "empty" if empty else result.status
    async with session.begin():
        session.add(
            AiSuggestion(
                id=suggestion_id,
                function=FUNCTION,
                alias=gateway.FUNCTION_ALIASES[FUNCTION],
                prompt_version=prompt.version,
                source=source.value,
                status=status,
                error_code=result.error_code or None,
                crm_user_id=employee.crm_user_id,
                created_at=clock.now(),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
            )
        )
    log.info("ai.letter_intake", suggestion_id=str(suggestion_id), status=status, source=source.value)
    if (result.status == "budget" or fields is None or empty) and by_rules is not None:
        return await _rules_suggestion(session, employee, by_rules)
    if result.status == "budget":
        raise conflict("ai_budget_exceeded", "Дневной лимит помощника исчерпан — заполните вручную.")
    if fields is None:
        raise conflict("ai_unavailable", "Помощник сейчас не ответил — заполните вручную или повторите позже.")
    if empty:
        raise conflict("nothing_recognized", "Помощник ничего не нашёл в файле — заполните вручную.")
    return LetterIntakeSuggestion(
        suggestion_id=suggestion_id,
        source=source,
        fields=fields,
        alias=gateway.FUNCTION_ALIASES[FUNCTION],
        prompt_version=prompt.version,
    )


async def decide(session: AsyncSession, employee: Employee, suggestion_id: uuid.UUID, decision: AiDecision) -> None:
    """Решение человека по предложению — только автор вызова (чужое — 404)."""
    done = await session.execute(
        update(AiSuggestion)
        .where(AiSuggestion.id == suggestion_id, AiSuggestion.crm_user_id == employee.crm_user_id)
        .values(decision=decision.value, decided_at=clock.now())
    )
    if getattr(done, "rowcount", 0) == 0:
        raise not_found("Предложение не найдено.")
