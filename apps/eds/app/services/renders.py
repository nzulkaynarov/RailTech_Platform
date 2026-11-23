"""PDF письма на бланке (P4): ввод рендера, кэш по хешу, фоновая задача, состояние для экрана (B-094).

- **Ввод** (`payload`) — тело письма с подписью, реквизиты письма (номер и дата — только у зарегистрированного),
  `draft: true` у всякого PDF, который не итоговый (SIGN-1, ADR-0024 п. 4: «ПРОЕКТ» на каждой странице, без номера и
  даты; у итогового ключа нет — хеш выпущенных PDF не меняется), бланк из
  проекции ERP и хеш логотипа. Хеш SHA-256 канонического JSON ввода — ключ кэша и имя файла: тот же ввод второй раз не
  рендерится, а строка `document_renders` с вводом — снимок выпущенного письма (ADR-0020 п. 7).
- **В запросе рендера нет**: `request` пишет строку `pending`, а задачу ставит вызывающий **после коммита**
  (`take_pending` → `Container.defer_render`); потерянную постановку подбирает `sweep` (раз в минуту).
- **Воркер** (`run`): рендер в отдельном процессе с тайм-аутом (`render_process.ProcessRenderer`), без открытой
транзакции
  на время вёрстки; PDF — в хранилище `renders/<хеш>.pdf`; затем `ready`/`failed` и отправка ждущих писем адресату.
"""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Final

import structlog
from rt_docs.labels import grid_label
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import clock
from app.config import get_settings
from app.errors import conflict
from app.models import Document, DocumentRender, Employee, Letter, LetterheadLogo
from app.schemas.documents import DocumentPdf
from app.services import letterhead
from app.services.people import load_directory
from app.services.render_process import BODY, LETTERHEAD, TIMEOUT, RenderError
from app.services.storage import ObjectStorage

log = structlog.get_logger(__name__)

RENDERER_VERSION: Final = (
    "rt-docs/letter-2"  # меняется вместе с вёрсткой письма — старый кэш не применяется (letter-2: сетка, ДОК-5)
)
LAYOUT: Final = "letter"
DEFAULT_ACCENT: Final = "#15294d"
SWEEP_AFTER: Final = timedelta(minutes=1)
_PENDING_KEY: Final = "rt_eds_render_defer"

LETTERHEAD_MISSING: Final = "Бланк компании не задан — администратор сохраняет Настройки · Компания и бланки."
_ERRORS: Final = {
    TIMEOUT: "Письмо слишком большое для PDF — сократите текст или разбейте таблицу.",
    BODY: "Текст письма не прошёл проверку бланка — проверьте списки и таблицы.",
    LETTERHEAD: "Бланк компании не подходит для печати — проверьте логотип и цвет в «Компания и бланки».",
}
_ERROR_OTHER: Final = "Не удалось построить PDF — нажмите «Повторить»; если не поможет, сообщите администратору."

Renderer = Callable[[dict[str, Any], bytes | None, str | None], Awaitable[dict[str, Any]]]

_REPLY_DATE = {"ru": "от", "uz": "", "en": "of"}


def digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def storage_key(render_hash: str) -> str:
    return f"renders/{render_hash}.pdf"


def error_text(failure: RenderError) -> str:
    return _ERRORS.get(failure.code, _ERROR_OTHER)


def _with_signature(body: dict[str, Any], name: str, position: str, basis_text: str | None = None) -> dict[str, Any]:
    """Тело письма + подпись (одна сторона) в конце: подпись ставит система, не редактор."""
    party: dict[str, Any] = {key: value for key, value in (("position", position), ("name", name)) if value}
    if basis_text:
        party["basis"] = basis_text
    if not party:
        return body
    doc = dict(body.get("doc") or {"type": "doc", "content": []})
    doc["content"] = [*list(doc.get("content") or []), {"type": "signature", "attrs": {"parties": [party]}}]
    return {**body, "doc": doc}


def _date_text(lang: str, value: Any) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


async def _reply_to(session: AsyncSession, document: Document, lang: str) -> str | None:
    """«На № … от …» — исх. № и дата отправителя входящего; без них — наш номер ВХ и дата поступления."""
    if document.in_reply_to is None:
        return None
    letter = await session.get(Letter, document.in_reply_to)
    if letter is None:
        return None
    number = letter.sender_ref_number or letter.number
    day = letter.sender_ref_date if letter.sender_ref_number else letter.received_at
    word = _REPLY_DATE.get(lang, "от")
    return f"№ {number} {word} {_date_text(lang, day)}".replace("  ", " ").strip() if day else f"№ {number}"


def info_row(label: str, value: str, *, code: bool = False, role: str = "") -> dict[str, Any]:
    """Строка инфоблока сетки в вводе рендера: `{label, value, code, role}` (rt_docs.InfoRow)."""
    return {"label": label, "value": value, "code": code, "role": role}


def grid_meta(
    lang: str,
    *,
    number: str | None,
    day: str | None,
    reply_to: str | None,
    executor: str | None,
    email: str | None,
    project: str | None,
    code: str | None,
    signed_text: str | None,
    memo: bool = False,
) -> dict[str, Any]:
    """Сетка письма (стандарт документов §4–§5): вид и инфоблок «метка — значение» вместо паспорта письма.

    Подписи — на языке письма (`rt_docs.labels`); первые две строки (номер, дата) — мини-инфоблок со 2-й страницы.
    Номер и дата проекта рендер заменяет сам, строка кода проверки есть только у итогового письма."""
    key: Any = lang if lang in ("ru", "uz", "en") else "ru"
    rows = [
        info_row(grid_label("number_out", key), number or "—", code=True, role="number"),
        info_row(grid_label("date", key), day or "—", role="date"),
    ]
    if memo:  # a memo is the compact sheet: no outgoing number, no window (standard §4)
        rows = [info_row(grid_label("date", key), day or "—", role="date")]
    if reply_to:
        rows.append(info_row(grid_label("reply_to", key), reply_to.removeprefix("№ ")))
    if project:
        rows.append(info_row(grid_label("project", key), project, code=True))
    if executor:
        rows.append(info_row(grid_label("executor", key), executor))
    if email:
        rows.append(info_row(grid_label("email", key), email))
    if code:
        rows.append(info_row(grid_label("verify", key), code, code=True, role="verify"))
    kind = "kind_memo" if memo else "kind_letter"
    return {"kind_label": grid_label(kind, key), "info": rows, "signed_text": signed_text}


def grid_letterhead(head: Any, lang: str) -> dict[str, Any]:
    """Бланк для рендера: название, реквизиты, подвал, цвет, шрифт + колонки подвала сетки и строка обратного адреса."""
    return {
        "company_name": letterhead.text(head, "company_name", lang),
        "requisites": letterhead.requisites(head, lang),
        "footer": letterhead.footer(head, lang),
        "accent": head.accent_color or DEFAULT_ACCENT,
        "font": head.font_family,
        "footer_columns": letterhead.footer_columns(head, lang),
        "return_address": letterhead.return_address(head, lang),
    }


def is_final(document: Document) -> bool:
    return document.status == "sent" and document.number is not None and document.registered_at is not None


async def build_payload(session: AsyncSession, document: Document) -> tuple[dict[str, Any], str | None]:
    """Ввод рендера письма; нет тела — 409 `no_body`, нет бланка — 409 `letterhead_missing`."""
    if document.kind != "letter_out" or document.body is None:
        raise conflict("no_body", "PDF на бланке строится только для письма с текстом блоками.")
    head = await letterhead.current(session)
    if head is None:
        raise conflict("letterhead_missing", LETTERHEAD_MISSING)
    lang = str(document.body.get("lang") or "ru")
    final = is_final(document)
    directory = await load_directory(session, [document.author_crm_user_id])
    name = (document.signatory_name or head.signatory_name).strip()
    position = (document.signatory_position or letterhead.text(head, "signatory_position", lang)).strip()
    # Окно конверта (стандарт §4): организация первой строкой (в сетке — полужирным), ниже должность и ФИО
    addressee = [line for line in (document.recipient_name, document.recipient_attention) if line and line.strip()]
    author = await session.get(Employee, document.author_crm_user_id)
    reply_to = await _reply_to(session, document, lang)
    registered = clock.company_date(document.registered_at) if final and document.registered_at else None
    day = registered.isoformat() if registered else None
    signed_text = (
        document.signed_at.astimezone(clock.COMPANY_TZ).strftime("%d.%m.%Y %H:%M")
        if final and document.signed_at
        else None
    )
    basis_text = document.signatory_basis_text if final else None
    verification_code = document.verification_code if final else None
    verification_url = f"https://{get_settings().cabinet_domain}/v/{verification_code}" if verification_code else None
    payload: dict[str, Any] = {
        "renderer": RENDERER_VERSION,
        "layout": LAYOUT,
        "body": _with_signature(document.body, name, position, basis_text=basis_text),
        "meta": {
            "number": document.number if final else None,
            "date": day,
            "addressee": addressee,
            "addressee_strong": 0 if document.recipient_name and document.recipient_name.strip() else None,
            "reply_to": reply_to,
            "executor": directory.name(document.author_crm_user_id),
            "basis_text": basis_text,
            "verification_code": verification_code,
            "verification_url": verification_url,
            **grid_meta(
                lang,
                number=document.number if final else None,
                day=_date_text(lang, registered),
                reply_to=reply_to,
                executor=directory.name(document.author_crm_user_id),
                email=author.email if author and author.email else None,
                project=document.deal_number,
                code=verification_code,
                signed_text=signed_text,
            ),
        },
        "letterhead": grid_letterhead(head, lang),
        "logo_sha256": head.logo_sha256,
    }
    if not final:
        payload["draft"] = True  # ключ только у проекта: у итогового ввод и хеш прежние (SIGN-1)
    return payload, head.logo_sha256


async def request_preview(session: AsyncSession, body: dict[str, Any], kind: str = "letter") -> DocumentRender:
    """Предпросмотр шаблона (TPL-4): тело на бланке без документа — проект с подписантом бланка, та же очередь и
    тот же кэш по хешу ввода, что у писем; нет бланка — 409 `letterhead_missing`."""
    head = await letterhead.current(session)
    if head is None:
        raise conflict("letterhead_missing", LETTERHEAD_MISSING)
    lang = str(body.get("lang") or "ru")
    memo = kind == "memo"
    payload: dict[str, Any] = {
        "renderer": RENDERER_VERSION,
        "layout": "internal" if memo else LAYOUT,
        "body": _with_signature(
            body, head.signatory_name.strip(), letterhead.text(head, "signatory_position", lang).strip()
        ),
        "meta": {
            "number": None,
            "date": None,
            "addressee": [],
            "reply_to": None,
            "executor": None,
            "basis_text": None,
            "verification_code": None,
            "verification_url": None,
            **grid_meta(
                lang,
                number=None,
                day=None,
                reply_to=None,
                executor=None,
                email=None,
                project=None,
                code=None,
                signed_text=None,
                memo=memo,
            ),
        },
        "letterhead": grid_letterhead(head, lang),
        "logo_sha256": head.logo_sha256,
        "draft": True,
        "preview": True,  # выдаётся по хешу только такой рендер — черновик чужого письма так не получить
    }
    render_hash = digest(payload)
    now = clock.now()
    await session.execute(
        insert(DocumentRender)
        .values(
            hash=render_hash,
            status="pending",
            final=False,
            payload=payload,
            logo_sha256=head.logo_sha256,
            attempts=0,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["hash"])
    )
    row = (
        await session.execute(select(DocumentRender).where(DocumentRender.hash == render_hash).with_for_update())
    ).scalar_one()
    if row.status == "failed":
        row.status, row.error, row.created_at, row.finished_at = "pending", None, now, None
    if row.status == "pending":
        _pending(session).append(render_hash)
    await session.flush()
    return row


def _pending(session: AsyncSession) -> list[str]:
    pending: list[str] = session.info.setdefault(_PENDING_KEY, [])
    return pending


def queue_after_commit(session: AsyncSession, render_hash: str) -> None:
    """Поставить рендер в очередь после коммита транзакции `session` (вызывающий — `take_pending` → `defer_render`)."""
    _pending(session).append(render_hash)


def take_pending(session: AsyncSession) -> list[str]:
    """Хеши рендеров, которые нужно поставить в очередь после коммита транзакции `session`."""
    return list(dict.fromkeys(session.info.pop(_PENDING_KEY, [])))


async def request(session: AsyncSession, document: Document) -> DocumentRender:
    """PDF письма по текущим данным: из кэша или новая строка `pending` (задача — после коммита)."""
    payload, logo_sha = await build_payload(session, document)
    render_hash = digest(payload)
    now = clock.now()
    await session.execute(
        insert(DocumentRender)
        .values(
            hash=render_hash,
            status="pending",
            final=is_final(document),
            payload=payload,
            logo_sha256=logo_sha,
            attempts=0,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["hash"])
    )
    row = (
        await session.execute(select(DocumentRender).where(DocumentRender.hash == render_hash).with_for_update())
    ).scalar_one()
    if row.status == "failed":  # повтор неудачного — только явным запросом
        row.status, row.error, row.created_at, row.finished_at = "pending", None, now, None
    if row.status == "pending":
        _pending(session).append(render_hash)
    document.pdf_hash = render_hash
    await session.flush()
    return row


def is_draft_render(row: DocumentRender) -> bool:
    """Проект: рендер не итоговый и ввод помечен `draft` (SIGN-1)."""
    return not row.final and bool(row.payload.get("draft"))


def is_unmarked_draft(row: DocumentRender) -> bool:
    """Не итоговый PDF без знака «ПРОЕКТ»: построен до SIGN-1 — не выдаётся, нужно запросить заново."""
    return not row.final and not row.payload.get("draft")


def present(row: DocumentRender) -> DocumentPdf:
    return DocumentPdf(
        status=row.status,
        final=row.final,
        error=row.error,
        pages=row.pages,
        requested_at=row.created_at,
        ready_at=row.finished_at if row.status == "ready" else None,
    )


async def stream(storage: ObjectStorage, row: DocumentRender) -> AsyncIterator[bytes]:
    if row.status != "ready" or row.storage_key is None:
        raise conflict("pdf_not_ready", "PDF ещё готовится.", status=row.status)
    async for chunk in storage.stream(row.storage_key):
        yield chunk


# --- воркер ---------------------------------------------------------------------------------------------------------

_LOCAL_LOCK = asyncio.Lock()  # параллельность 1 и внутри процесса воркера (между процессами — `lock` задачи)

OnReady = Callable[[AsyncSession, DocumentRender], Awaitable[None]]


async def run(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    renderer: Renderer,
    render_hash: str,
    *,
    on_finished: OnReady | None = None,
) -> str | None:
    """Задача воркера: отрендерить `pending` и записать итог. Возвращает статус (`None` — нечего делать)."""
    async with _LOCAL_LOCK:
        async with session_factory() as session, session.begin():
            row = await session.get(DocumentRender, render_hash)
            if row is None or row.status != "pending":
                return None
            payload = dict(row.payload)
            logo = await session.get(LetterheadLogo, row.logo_sha256) if row.logo_sha256 else None
            logo_data, logo_mime = (logo.data, logo.content_type) if logo else (None, None)
            requested_at = row.created_at
        result: dict[str, Any] | None = None
        error: str | None = None
        try:
            result = await renderer(payload, logo_data, logo_mime)
            await storage.put(storage_key(render_hash), result["pdf"], "application/pdf")
        except RenderError as failure:
            error = error_text(failure)
            log.warning("render_failed", render=render_hash, code=failure.code, detail=failure.detail[:300])
        async with session_factory() as session, session.begin():
            row = await session.get(DocumentRender, render_hash, with_for_update=True)
            if row is None or row.status != "pending" or row.created_at != requested_at:
                return None  # повторный запрос после ошибки уже переставил строку — итог этой попытки не нужен
            row.attempts += 1
            row.finished_at = clock.now()
            if result is not None:
                row.status, row.error = "ready", None
                row.storage_key, row.size = storage_key(render_hash), len(result["pdf"])
                row.pages, row.last_page_fill = int(result["pages"]), float(result["last_page_fill"])
            else:
                row.status, row.error = "failed", error
            if on_finished is not None:
                await on_finished(session, row)
            log.info("render_finished", render=render_hash, status=row.status, pages=row.pages)
            return row.status


async def stale_pending(session: AsyncSession, now: datetime) -> list[str]:
    """Хеши `pending`, запрошенные раньше минуты назад: постановку в очередь могли потерять."""
    rows = await session.execute(
        select(DocumentRender.hash).where(
            DocumentRender.status == "pending", DocumentRender.created_at < now - SWEEP_AFTER
        )
    )
    return list(rows.scalars())


__all__ = [
    "LETTERHEAD_MISSING",
    "build_payload",
    "digest",
    "is_draft_render",
    "is_final",
    "is_unmarked_draft",
    "present",
    "request",
    "run",
    "stale_pending",
    "storage_key",
    "stream",
    "take_pending",
]
