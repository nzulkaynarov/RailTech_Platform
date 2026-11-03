"""«Заполнить из файла» — ИИ-помощник регистрации входящего (EDS-REG; стандарт ИИ-помощника — исследование
`docs/research/2026-11-02-flexibility/5-ai-assist.md` §4; правила юриста — DECISIONS 2026-11-02).

* Только по кнопке: сервис вызывается из `POST /letter-intake`, ничего не пишет в письмо — предлагает поля.
* PDF с текстовым слоем: текст извлекает EDS (`pypdf`), персональные данные маскирует код (`security/pii.py`), в модель
  уходит только маскированный текст; метки номеров `[number_N]` в ответе код возвращает локально.
* Скан или фото без текста — модель с изображением, только при серверной настройке `recognize_scans` (по умолчанию
  выключена, в интерфейсе переключателя нет до решения владельца и юриста — `docs/QUESTIONS.md`, Q-EDSREG-1).
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


def clean(
    data: dict[str, Any], *, masked: Masked | None, kinds: set[str], raw: str, today: date, own_inn: str | None = None
) -> LetterIntakeFields:
    """Ответ модели → поля карточки: код решает, что принять (вид — из справочника, даты — разобранные и в разумных
    пределах, ИНН — найденный кодом, не свой)."""
    ref_date = _date(data.get("sender_ref_date"))
    due = _date(data.get("document_due"))
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
    session: AsyncSession, settings: Settings, storage: ObjectStorage, employee: Employee, file_id: uuid.UUID
) -> LetterIntakeSuggestion:
    """Предложить поля карточки по файлу письма. Вызов модели — вне транзакции, журнал — своей транзакцией."""
    async with session.begin():
        await files.load_visible(session, employee, file_id)
        version = await files.get_version(session, file_id, None)
        scans_on = await docflow_settings.recognize_scans(session)
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
    if not gateway.available(settings):
        raise conflict("ai_unavailable", "Помощник не настроен — заполните вручную.")
    budget = Decimal(str(settings.ai_daily_budget_usd))
    if budget > 0 and spent >= budget:  # 0 — без лимита (как у ERP)
        raise conflict("ai_budget_exceeded", "Дневной лимит помощника исчерпан — заполните вручную.")
    data = await _read(storage, version.s3_key)
    try:
        raw = await asyncio.to_thread(pdf_text, data) if version.content_type == PDF else ""
    except TooManyPagesError as exc:
        raise conflict(
            "file_too_large", f"В файле больше {MAX_PDF_PAGES} страниц — это не письмо. Заполните вручную."
        ) from exc
    source = IntakeSource.TEXT if len(raw) >= MIN_TEXT else IntakeSource.IMAGE
    if source is IntakeSource.IMAGE and not scans_on:
        raise conflict("scan_recognition_disabled", "Это скан или фото: помощник их пока не читает. Заполните вручную.")
    if source is IntakeSource.IMAGE and len(data) > MAX_IMAGE_BYTES:
        raise conflict("file_too_large", _too_large(MAX_IMAGE_BYTES))

    masked = mask_numbered(raw) if source is IntakeSource.TEXT else None
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
            today=clock.company_date(clock.now()),
            own_inn=own_inn,
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
