"""Ссылка документа в Кабинет (ДК-1, ДК-2, ADR-0030): выпуск, состояние, код-вход, действие, отзыв.

Что здесь гарантируется:

* ссылка — на получателя: токен 256 бит, в базе только SHA-256; адрес получателя записывается при выпуске и из
  запроса не берётся — код уходит только на него;
* ссылка живёт до срока документа плюс `LINK_GRACE_DAYS` и отзывается отправителем; новая версия КП отзывает ссылки
  старой (состояние `superseded` выводится из фактов, а не хранится);
* код — шесть цифр, `CODE_TTL`, пять попыток на код и на ссылку, повтор не раньше `CODE_RESEND_SECONDS`, не больше
  `CODE_MAX_PER_HOUR` в час на ссылку; в базе — HMAC кода, как у входа по письму (`login_code`);
* код — это вход: после него открыта сессия контакта-получателя, права — те, что сотрудник задал контакту;
* неизвестный токен — один и тот же ответ (404), у отозванной и просроченной ссылки — только причина.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from parties.models import Contact, active_contact_q
from portal.exceptions import PortalDeliveryFailed, PortalGone, PortalTooManyRequests, PortalValidationError
from portal.models import DocumentLink, DocumentLinkEvent, DocumentLinkKind, MagicLinkToken
from portal.services import projections_link
from portal.services.access import company_has_cabinet_access
from portal.services.doc_link_kinds import GRACE_DAYS, select_related_all, spec_for, spec_of
from portal.services.login_code import generate_login_code, hash_login_code
from portal.services.tokens import generate_token, hash_token, issue_portal_session
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

#: Ссылка живёт столько дней после срока документа (ADR-0030 п. 6).
LINK_GRACE_DAYS = GRACE_DAYS
#: Срок ссылки у документа без срока действия.
LINK_FALLBACK_DAYS = 90
CODE_TTL = timedelta(minutes=10)
CODE_RESEND_SECONDS = 45
CODE_MAX_ATTEMPTS = 5
CODE_MAX_PER_HOUR = 6
#: Что можно сделать по ссылке; `open` — «открыть остальной кабинет» (только код, без действия над документом).
#: Какие из них доступны у вида документа — `doc_link_kinds.KindSpec.actions`.
ACTIONS = ("accept", "reject", "question", "open")

#: Причина, по которой ссылка ничего не показывает (код `detail` ответа 410).
LINK_GONE_CODES = {
    "revoked": "DOC_LINK_REVOKED",
    "expired": "DOC_LINK_EXPIRED",
    "superseded": "DOC_LINK_SUPERSEDED",
}


@dataclass(frozen=True)
class ClientContext:
    """Кто смотрит: `none` — гость; `member` — вошёл контакт той же компании; `other_company` — чужая сессия."""

    relation: str
    session: Optional[object] = None


# ── Выпуск ───────────────────────────────────────────────────────────────────────────────────────────────────────


def cabinet_url() -> str:
    return getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")


def build_url(raw_token: str) -> str:
    """Адрес ссылки в письме: `<кабинет>/d/<токен>`; токен — часть пути, а не фрагмент: ссылку открывают из почтовых
    программ, которые фрагмент иногда режут, а сам токен ни на какой сервер, кроме ERP, не уходит."""
    return f"{cabinet_url()}/d/{raw_token}"


def _link_expiry(quote) -> datetime:
    return spec_of("quote").expiry(quote)


def _recipient_contact(quote, email: str, name: str) -> Optional[Contact]:
    return deal_recipient_contact(quote.deal, email, name)


def deal_recipient_contact(deal, email: str, name: str) -> Optional[Contact]:
    """Контакт кабинета для адреса получателя: назначенный в заявке или найденный в компании по адресу; иначе `None`.

    Адрес получателя документа контактом компании НЕ становится (ADR-0030 п. 7, поправка 2026-11-25): одна опечатка
    или пересылка открыла бы чужому человеку весь кабинет клиента. Ссылка без контакта — гостевая: один документ и
    его PDF, без кода, сессии и действий (`availability` → `no_contact`). Контакт добавляет сотрудник явно.
    """
    chosen = getattr(deal, "contact", None)
    if chosen is not None and (chosen.email or "").strip().lower() == email.lower():
        return chosen
    if deal.company_id is None:
        return None
    return (
        Contact.objects.filter(active_contact_q(), company_id=deal.company_id, email__iexact=email)
        .order_by("-is_primary", "pk")
        .first()
    )


def mint_document_link(kind: str, doc, email: str, name: str, *, created_by=None) -> tuple[DocumentLink, str]:
    """Новая ссылка на договор, счёт или акт для получателя `email`; `(запись, сырой токен)` (ДК-3).

    Получатель — контакт компании сделки по адресу; нет такого — гостевая ссылка без контакта (как у КП).
    """
    spec = spec_of(kind)
    raw = generate_token()
    link = DocumentLink.objects.create(
        token_hash=hash_token(raw),
        kind=kind,
        **{kind: doc},
        contact=spec.recipient_contact(doc, email.strip(), name),
        recipient_email=email.strip().lower(),
        created_by=created_by,
        expires_at=spec.expiry(doc),
    )
    return link, raw


def deal_recipients(deal) -> list[tuple[str, str]]:
    """Кому уходят документы и письма сделки: `(адрес, имя)` без повторов (ДК-3, ADR-0030 п. 8).

    Контакт сделки и каждый, кому уже уходил документ сделки (получатель КП, договора, счёта, акта); если таких нет —
    основной контакт компании, затем зарегистрированный покупатель. Прежние участники компании в ERP письма о документах
    не получают.
    """
    found: dict[str, str] = {}

    def add(email, name):
        key = (email or "").strip().lower()
        if key and key not in found:
            found[key] = name or key

    contact = getattr(deal, "contact", None)
    if contact is not None and not contact.is_archived:
        add(contact.email, contact.name)
    for link in document_links_of_deal(deal).select_related("contact"):
        if link.contact is not None and link.contact.is_archived:
            continue
        add(link.recipient_email, link.contact.name if link.contact is not None else "")
    if not found and deal.company_id is not None:
        primary = (
            Contact.objects.filter(active_contact_q(), company_id=deal.company_id)
            .exclude(email="")
            .order_by("-is_primary", "pk")
            .first()
        )
        if primary is not None:
            add(primary.email, primary.name)
    client = getattr(deal, "client", None)
    if not found and client is not None and client.email:
        add(client.email, client.get_full_name() or client.email)
    return list(found.items())


def document_links_of_deal(deal):
    from django.db.models import Q

    # Только не отозванные: отозванная ссылка — «письмо ушло не тому», такой адрес получателем сделки не становится
    return DocumentLink.objects.filter(
        Q(quote__deal=deal) | Q(contract__deal=deal) | Q(invoice__deal=deal) | Q(act__deal=deal),
        revoked_at__isnull=True,
    )


def document_contact_ids(deal) -> tuple[int, ...]:
    """Контакты сделки, которым письма-уведомления идут и без приглашения в кабинет: контакт сделки и получатели
    её документов (ADR-0030 п. 8)."""
    ids = {pk for pk in [getattr(deal, "contact_id", None)] if isinstance(pk, int)}
    ids.update(document_links_of_deal(deal).exclude(contact__isnull=True).values_list("contact_id", flat=True))
    return tuple(sorted(ids))


def mint_quote_link(quote, *, created_by=None) -> tuple[DocumentLink, str]:
    """Новая ссылка на КП для его получателя; `(запись, сырой токен)`. Нет получателя — `ValueError`."""
    from crm.services.quotes._shared import resolve_quote_recipient

    recipient = resolve_quote_recipient(quote)
    if recipient is None:
        raise ValueError("RECIPIENT_REQUIRED")
    email, name = recipient
    raw = generate_token()
    link = DocumentLink.objects.create(
        token_hash=hash_token(raw),
        kind=DocumentLinkKind.QUOTE,
        quote=quote,
        contact=_recipient_contact(quote, email.strip(), name),
        recipient_email=email.strip().lower(),
        created_by=created_by,
        expires_at=_link_expiry(quote),
    )
    return link, raw


def _legacy_raw(old_token: str) -> str:
    """Токен ссылки, в которую переводится старая ссылка страницы ERP: выводится из неё ключом сервера, поэтому каждый
    переход ведёт в ту же запись, а старый токен не получает прав на что-то, кроме этого КП."""
    digest = hmac.new(settings.SECRET_KEY.encode(), f"doc-link-legacy:{old_token}".encode(), hashlib.sha256)
    return digest.hexdigest()


def legacy_redirect_url(quote) -> Optional[str]:
    """Адрес Кабинета для старой ссылки `…/public/quotes/<токен>/`; `None` — получателя нет (остаётся страница ERP)."""
    from crm.services.quotes._shared import resolve_quote_recipient

    old_token = quote.public_access_token
    recipient = resolve_quote_recipient(quote)
    if not old_token or recipient is None:
        return None
    raw = _legacy_raw(old_token)
    email, name = recipient
    link = DocumentLink.objects.filter(token_hash=hash_token(raw)).first()
    if link is None:
        link, _created = DocumentLink.objects.get_or_create(
            token_hash=hash_token(raw),
            defaults={
                "kind": DocumentLinkKind.QUOTE,
                "quote": quote,
                "contact": _recipient_contact(quote, email.strip(), name),
                "recipient_email": email.strip().lower(),
                "expires_at": quote.public_token_expires_at or _link_expiry(quote),
                "legacy": True,
            },
        )
    return build_url(raw)


# ── Состояние ────────────────────────────────────────────────────────────────────────────────────────────────────


def find_link(raw_token: str) -> Optional[DocumentLink]:
    if not raw_token or len(raw_token) > 200:
        return None
    return DocumentLink.objects.filter(token_hash=hash_token(raw_token)).select_related(*select_related_all()).first()


def link_gone_reason(link: DocumentLink) -> Optional[str]:
    """`revoked`, `expired`, `superseded` или `None` (живая). Порядок: отзыв сильнее срока."""
    doc = link.document
    # Отзыв — на самой ссылке: флаг старой страницы КП (`public_token_revoked`) новые ссылки не гасит — после отзыва
    # отправитель может послать КП заново и получатель получит свежую ссылку.
    if link.revoked_at is not None or doc is None:
        return "revoked"
    if link.expires_at < timezone.now():
        return "expired"
    spec = spec_for(link)
    if not spec.visible(doc):
        return (
            "revoked"  # КП вернули в черновик, договор отозван, счёт отменён: клиенту документ больше не показывается
        )
    if spec.superseded(doc):
        return "superseded"
    return None


def raise_if_gone(link: DocumentLink) -> None:
    reason = link_gone_reason(link)
    if reason is not None:
        raise PortalGone(LINK_GONE_CODES[reason])


def client_context(link: DocumentLink, session) -> ClientContext:
    if session is None:
        return ClientContext("none")
    company_id = spec_for(link).company_id(link.document)
    if company_id is not None and session.company_id == company_id:
        return ClientContext("member", session)
    return ClientContext("other_company", session)


def availability(link: DocumentLink, ctx: ClientContext, modules=()) -> dict:
    """Что кнопки документа могут: `allowed` и причина отказа (`reason`) — для неактивной кнопки с подписью.

    Решение (принять, вернуть, вопрос) — только пока КП ждёт ответа, и только тому, у кого есть право действовать:
    у вошедшего это его контакт, у гостя — контакт-получатель, которым он станет после кода.
    """
    spec = spec_for(link)
    if not spec.actions:
        return {"allowed": False, "reason": "no_actions"}  # счёт: реквизиты и справка, действий нет
    state = spec.state(link.document)
    if state != "open":
        return {"allowed": False, "reason": state}  # accepted / rejected / expired
    if ctx.relation == "other_company":
        return {"allowed": False, "reason": "other_company"}
    contact = ctx.session.contact if ctx.relation == "member" else link.contact
    if contact is None:
        return {"allowed": False, "reason": "no_contact"}
    if ctx.relation == "member" and spec.module not in set(modules):
        return {"allowed": False, "reason": "no_access"}
    if not contact.can_act:
        return {"allowed": False, "reason": "no_right"}
    return {"allowed": True, "reason": None}


# ── Журнал ───────────────────────────────────────────────────────────────────────────────────────────────────────


def record_event(link: DocumentLink, event: str, *, ip: str = "", user_agent: str = "", action: str = "") -> None:
    DocumentLinkEvent.objects.create(
        link=link, event=event, action=action, ip_address=ip or None, user_agent=(user_agent or "")[:200]
    )


def _timeline(link: DocumentLink, title: str, event_code: str, **params) -> None:
    from crm.services.quotes._shared import _log_quote

    if link.kind == "quote":
        quote = link.quote
        _log_quote(
            quote,
            None,
            title,
            f"КП v{quote.version} ({quote.number or '—'})",
            event_code=event_code,
            event_params={"version": quote.version, "number": quote.number or "—", **params},
        )
        return
    spec_for(link).journal(
        link.document, action=title, event_code=event_code.replace("quote.", f"{link.kind}.", 1), **params
    )


def record_open(link: DocumentLink, *, ip: str = "", user_agent: str = "") -> None:
    """Открытие ссылки гостем или контактом: журнал, счётчик и (один раз за КП) отметка «просмотрено»."""
    now = timezone.now()
    DocumentLink.objects.filter(pk=link.pk).update(
        open_count=F("open_count") + 1, last_opened_at=now, first_opened_at=link.first_opened_at or now
    )
    record_event(link, DocumentLinkEvent.Event.OPENED, ip=ip, user_agent=user_agent)
    if link.kind == "quote":
        from crm.services.public_page import record_quote_view

        record_quote_view(link.quote, request_ip=ip)


_WORDS = {
    "quote": "КП",
    "contract": "договор",
    "invoice": "счёт",
    "act": "акт",
    "price_request": "запрос цены",
    "supplier_order": "заказ поставщику",
}


def _side(link: DocumentLink, client: str, partner: str) -> str:
    """Кто получатель ссылки в журнале: клиент заявки или партнёр-поставщик (ДК-5)."""
    return partner if spec_for(link).partner else client


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


# ── Код ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _failures_key(link: DocumentLink) -> str:
    return f"portal:doc-link-failures:{link.pk}"


def _can_receive_code(link: DocumentLink) -> bool:
    contact = link.contact
    return bool(
        contact is not None
        and contact.email
        and not contact.is_archived
        and company_has_cabinet_access(contact.company_id)
    )


def request_code(link: DocumentLink, *, ip: str = "", user_agent: str = "") -> dict:
    """Выпустить код и отправить на адрес получателя; ответ — куда ушло (замаскировано) и сколько ждать до повтора.

    Один код активен всегда: новый гасит прежний и обнуляет счёт неверных попыток ссылки.
    """
    if not _can_receive_code(link):
        raise PermissionDenied("FORBIDDEN")
    contact = link.contact
    code = generate_login_code()
    now = timezone.now()
    with transaction.atomic():
        locked = DocumentLink.objects.select_for_update().get(pk=link.pk)
        recent = list(
            MagicLinkToken.objects.filter(document_link=locked, created_at__gte=now - timedelta(hours=1)).order_by(
                "-created_at"
            )
        )
        if recent:
            wait = CODE_RESEND_SECONDS - int((now - recent[0].created_at).total_seconds())
            if wait > 0:
                raise PortalTooManyRequests("CODE_RESEND_TOO_SOON", retry_after=wait)
        if len(recent) >= CODE_MAX_PER_HOUR:
            raise PortalTooManyRequests("TOO_MANY_REQUESTS", retry_after=600)
        MagicLinkToken.objects.filter(document_link=locked, used_at__isnull=True).update(used_at=now)
        MagicLinkToken.objects.create(
            token_hash=hash_token(generate_token()),  # сырого токена у кода нет: гасится только вместе со ссылкой
            code_hash=hash_login_code(contact.pk, code),
            contact=contact,
            purpose=MagicLinkToken.PURPOSE_DOCUMENT,
            document_link=locked,
            expires_at=now + CODE_TTL,
        )
        cache.delete(_failures_key(locked))
        # Бот — раньше письма: ошибка письма откатывает и событие; сбой самого бота (savepoint) код не отменяет
        try:
            to_telegram = _send_code_telegram(locked, code, now + CODE_TTL)
        except Exception:  # noqa: BLE001 — почта основной канал: сбой бота (кэш секрета, шина) не отменяет код
            logger.exception("Document link code telegram event failed (link %s)", locked.pk)
            to_telegram = False
        _send_code_email(locked, code)
        record_event(locked, DocumentLinkEvent.Event.CODE_SENT, ip=ip, user_agent=user_agent)
        _timeline(
            locked,
            f"{_side(locked, 'Клиенту', 'Партнёру')} отправлен код по ссылке на {_WORDS[locked.kind]}",
            "quote.link_code_sent",
        )
    return {
        "sent_to": mask_email(contact.email),
        "expires_in": int(CODE_TTL.total_seconds()),
        "resend_after": CODE_RESEND_SECONDS,
        "channels": ["email", "telegram"] if to_telegram else ["email"],
    }


def _telegram_ready(contact: Optional[Contact]) -> bool:
    """У получателя привязан Telegram и контакт с компанией сопоставлены с CRM — бот может ему написать (ДК-4)."""
    from portal.services.acceptance import _telegram_deliverable

    return contact is not None and _telegram_deliverable(contact)


def _send_code_telegram(link: DocumentLink, code: str, expires_at: datetime) -> bool:
    """Тот же код — ещё и в бот получателя, если у него привязан Telegram (ДК-4); `True` — событие выпущено.

    Код, его срок, повтор и попытки — те же, что у письма: здесь только второй канал. Сообщение несёт код и срок, данных
    документа в нём нет. Ошибка публикации — наружу из savepoint; вызывающий `request_code` её ловит: почта остаётся основным каналом.
    """
    contact = link.contact
    if spec_for(link).partner or not _telegram_ready(contact):
        return False  # ДК-5: событие знает только документы клиента (`document_kind`); партнёру — письмо
    from integration.services import events

    with transaction.atomic():
        event = events.publish_document_link_telegram(
            contact,
            kind="code",
            document_kind=link.kind,
            code=code,
            expires_at=expires_at,
        )
    return event is not None


def _telegram_documents_wanted(contact: Contact) -> bool:
    """Контакт не отключил в кабинете Telegram-уведомления о документах."""
    return ((contact.notification_settings or {}).get("documents") or {}).get("telegram") is not False


def quote_link_telegram_user_id(quote, channels=None) -> Optional[int]:
    """Telegram, в который уйдёт личная ссылка этого КП (ДК-4), — чтобы старое «КП готово» туда не дублировалось.

    Тот же отбор, что у `send_link_telegram`: письмо с КП уходит (`channels` без `email` — нет), получатель — контакт
    заявки или найденный в компании по адресу (нового здесь не заводим), у него привязан Telegram и он не отключил
    уведомления о документах. Иначе `None`: бот шлёт прежнее сообщение.
    """
    from crm.services.quotes._shared import resolve_quote_recipient

    if channels is not None and "email" not in channels:
        return None
    recipient = resolve_quote_recipient(quote)
    deal = quote.deal
    if recipient is None or deal.company_id is None:
        return None
    email = recipient[0].strip()
    chosen = getattr(deal, "contact", None)
    contact = chosen if chosen is not None and (chosen.email or "").strip().lower() == email.lower() else None
    if contact is None:
        contact = (
            Contact.objects.filter(active_contact_q(), company_id=deal.company_id, email__iexact=email)
            .order_by("-is_primary", "pk")
            .first()
        )
    if contact is None or not _telegram_ready(contact) or not _telegram_documents_wanted(contact):
        return None
    return contact.telegram_user_id


def send_link_telegram(link: DocumentLink, raw_token: str) -> bool:
    """Личная ссылка документа — ещё и в бот получателя, если у него привязан Telegram (ДК-4); `True` — событие выпущено.

    Одно короткое сообщение: вид документа, номер, продавец и кнопка на `/d/<токен>`. Контакт, отключивший в кабинете
    Telegram-уведомления о документах, ссылку в бот не получает (письмо остаётся). Ошибку публикации ловит вызывающая
    задача: письмо уже ушло, повтор задачи послал бы его второй раз.
    """
    contact = link.contact
    if spec_for(link).partner or not _telegram_ready(contact):
        return False  # ДК-5: см. `_send_code_telegram`
    if not _telegram_documents_wanted(contact):
        return False
    from integration.services import events

    spec = spec_for(link)
    doc = link.document
    with transaction.atomic():
        event = events.publish_document_link_telegram(
            contact,
            kind="link",
            document_kind=link.kind,
            number=spec.number(doc) or "",
            seller_name=spec.seller_name(doc) or "",
            url=build_url(raw_token),
        )
    return event is not None


def _seller_company(link: DocumentLink):
    """Компания-продавец документа для рамки письма (бренд); `None` — нейтральная рамка платформы."""
    if link.kind == "quote":
        return link.quote.seller_company
    if spec_for(link).partner:
        from supply.services.partner_documents import buyer_company

        return buyer_company()  # документ партнёра — от нас, «продавца» нет
    from crm.services.billing import _invoice_seller_company
    from crm.services.quotes import _quote_seller_company

    doc = link.document
    if link.kind == "contract":
        return _quote_seller_company(doc.quote) if doc.quote_id else None
    invoice = doc if link.kind == "invoice" else doc.invoice
    return _invoice_seller_company(invoice) if invoice is not None else None


def _send_code_email(link: DocumentLink, code: str) -> None:
    from notifications.emails import email_brand, send_templated_email

    spec = spec_for(link)
    doc = link.document
    contact = link.contact
    seller = _seller_company(link)
    try:
        send_templated_email(
            "document_link_code",
            {
                "code": code,
                "document_number": spec.number(doc) or f"{doc.pk}",
                "seller_name": spec.seller_name(doc),
                "expires_minutes": int(CODE_TTL.total_seconds() // 60),
                **email_brand(seller),
            },
            to=[contact.email.strip().lower()],
            channel="transactional",
            language=contact.language,
            redact=(code,),
        )
    except Exception as exc:  # noqa: BLE001 — сбой почты не прячем: код не выпущен, клиент должен узнать
        logger.exception("Document link code mail failed (link %s)", link.pk)
        raise PortalDeliveryFailed("DELIVERY_FAILED") from exc


def verify_code(link: DocumentLink, code: str, *, ip: str = "", user_agent: str = ""):
    """Погасить код ссылки и открыть сессию контакта-получателя; `(сессия, сырой токен)`.

    Неверный, просроченный или чужой (от другой ссылки) код — 422 `LOGIN_CODE_INVALID`; после пяти неверных подряд — 429
    `LOGIN_CODE_LOCKED`, пока не выпущен новый код.
    """
    from portal.exceptions import PortalTooManyRequests as TooMany

    if int(cache.get(_failures_key(link)) or 0) >= CODE_MAX_ATTEMPTS:
        raise TooMany("LOGIN_CODE_LOCKED")
    contact = link.contact
    if contact is None:
        raise PermissionDenied("FORBIDDEN")
    supplied = hash_login_code(contact.pk, (code or "").strip())
    now = timezone.now()
    with transaction.atomic():
        candidates = list(
            MagicLinkToken.objects.select_for_update(of=("self",))
            .filter(document_link=link, used_at__isnull=True, expires_at__gt=now, code_attempts__lt=CODE_MAX_ATTEMPTS)
            .order_by("-created_at")
        )
        match = None
        for row in candidates:  # сравниваем со всеми: время ответа не зависит от того, какая запись подошла
            if hmac.compare_digest(row.code_hash, supplied) and match is None:
                match = row
        if match is None:
            if candidates:
                MagicLinkToken.objects.filter(pk__in=[row.pk for row in candidates]).update(
                    code_attempts=F("code_attempts") + 1
                )
            result = None
        else:
            if not _can_receive_code(link):
                raise PermissionDenied("FORBIDDEN")
            match.used_at = now
            match.save(update_fields=["used_at"])
            result = issue_portal_session(contact, "magic_link", ip_address=ip or None, user_agent=user_agent)
            if contact.invited_at is None:
                Contact.objects.filter(pk=contact.pk, invited_at__isnull=True).update(invited_at=now)
            record_event(link, DocumentLinkEvent.Event.CODE_USED, ip=ip, user_agent=user_agent)
            _timeline(
                link,
                f"{_side(link, 'Клиент', 'Партнёр')} подтвердил код по ссылке на {_WORDS[link.kind]}",
                "quote.link_code_used",
            )
    if result is not None:
        cache.delete(_failures_key(link))
        return result
    key = _failures_key(link)
    cache.add(key, 0, int(CODE_TTL.total_seconds()))
    try:
        failures = int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, int(CODE_TTL.total_seconds()))
        failures = 1
    record_event(link, DocumentLinkEvent.Event.CODE_FAILED, ip=ip, user_agent=user_agent)
    if failures >= CODE_MAX_ATTEMPTS:
        raise TooMany("LOGIN_CODE_LOCKED")
    raise PortalValidationError("LOGIN_CODE_INVALID")


# ── Отзыв ────────────────────────────────────────────────────────────────────────────────────────────────────────


def revoke_quote_links(quote, actor) -> int:
    """Отозвать все живые ссылки КП (и страницу ERP); возвращает, сколько записей отозвано. Повтор — ноль."""
    return revoke_document_links("quote", quote, actor)


def revoke_document_links(kind: str, doc, actor) -> int:
    """Отозвать ВСЕ живые ссылки документа — у каждого получателя; ссылки других документов не трогаются (ДК-3)."""
    now = timezone.now()
    ids = DocumentLink.objects.filter(kind=kind, revoked_at__isnull=True, **{kind: doc}).values_list("pk", flat=True)
    revoked = 0
    for pk in list(ids):
        # Условное обновление: параллельный отзыв той же ссылки не считается и не пишется в журнал второй раз
        if DocumentLink.objects.filter(pk=pk, revoked_at__isnull=True).update(revoked_at=now, revoked_by=actor):
            record_event(DocumentLink(pk=pk), DocumentLinkEvent.Event.REVOKED)
            revoked += 1
    return revoked


def revoke_document_links_logged(kind: str, doc, actor) -> int:
    """«Отозвать ссылку» из карточки договора, счёта или акта (ДК-3б): отзыв всех живых ссылок документа и событие в
    журнале сделки — кто и когда; повтор без живых ссылок ничего не пишет."""
    count = revoke_document_links(kind, doc, actor)
    if count:
        spec_of(kind).journal(
            doc, action=f"Ссылка на {_WORDS[kind]} отозвана", event_code=f"{kind}.link_revoked", user=actor, links=count
        )
    return count


def document_link_rows(kind: str, doc) -> list[dict]:
    """Ссылки получателей документа для карточки в Платформе: адрес только замаскированный, состояние выводится из тех же
    фактов, по которым ссылка открывается у клиента (`link_gone_reason`): `active`, `revoked`, `expired`, `superseded`.
    Новые сверху; ссылки других документов не попадают."""
    links = (
        DocumentLink.objects.filter(kind=kind, **{kind: doc})
        .select_related(*select_related_all())
        .order_by("-created_at", "-pk")
    )
    return [
        {
            "id": link.pk,
            "recipient_hint": mask_email(link.recipient_email),
            "sent_at": link.created_at,
            "first_opened_at": link.first_opened_at,
            "last_opened_at": link.last_opened_at,
            "expires_at": link.expires_at,
            "state": link_gone_reason(link) or "active",
        }
        for link in links
    ]


# ── Что видит отправитель ────────────────────────────────────────────────────────────────────────────────────────


def _old_page_expiry(quote) -> Optional[datetime]:
    """Когда гаснет старая страница ERP: срок токена, иначе конец последнего дня `valid_until`; `None` — без срока."""
    if quote.public_token_expires_at:
        return quote.public_token_expires_at
    if quote.valid_until:
        return timezone.make_aware(datetime.combine(quote.valid_until, time.max))
    return None


def client_link_summary(quote) -> Optional[dict]:
    """Ссылка клиента для карточки КП в Платформе: `none`/`active`/`revoked`/`expired`/`superseded`, адрес и открытия.

    Состояние выводится из тех же фактов, по которым ссылка открывается у клиента (`link_gone_reason`,
    `public_quote_gate`), а не из наличия записей. `None` — КП клиенту ещё не уходило. Старая ссылка страницы ERP
    (разослана до перехода, записей ссылок нет) живёт, пока её пропускает старый затвор: он же решает, куда ведёт
    переход — в живой документ или в причину.
    """
    if quote.frozen_at is None:
        return None
    links = list(quote.document_links.all())
    superseded = projections_link.newer_sent_version(quote) is not None
    live = [link for link in links if link_gone_reason(link) is None]
    expires_at = max((link.expires_at for link in live), default=None)
    if live:
        state = "active"
    elif links:
        reasons = {link_gone_reason(link) for link in links}
        state = "superseded" if "superseded" in reasons else "expired" if "expired" in reasons else "revoked"
    elif quote.public_access_token:
        from crm.services.quotes import public_quote_gate

        gate = public_quote_gate(quote)
        if gate is None:
            state = "superseded" if superseded else "active"
            expires_at = _old_page_expiry(quote)
        else:
            state = "revoked" if gate == "QUOTE_LINK_REVOKED" else "expired"
    else:
        state = "none"
    opened = [link.first_opened_at for link in links if link.first_opened_at]
    last = [link.last_opened_at for link in links if link.last_opened_at]
    recipient = links[0].recipient_email if links else None
    if recipient is None:
        from crm.services.quotes._shared import resolve_quote_recipient

        resolved = resolve_quote_recipient(quote)
        recipient = resolved[0] if resolved else None
    return {
        "state": state,
        "recipient_hint": mask_email(recipient) if recipient else None,
        "expires_at": expires_at,
        "first_opened_at": min(opened, default=quote.first_viewed_at),
        "last_opened_at": max(last, default=quote.first_viewed_at),
    }


# ── Контакты, заведённые прежним выпуском ссылок (В-1, поправка к ADR-0030 п. 7) ─────────────────────────────────────


def auto_created_document_contacts() -> list[dict]:
    """Контакты, которые прежняя выдача ссылок завела по адресу получателя: без автора, без прав и без телефона, созданные
    в ту же минуту, что первая ссылка на них, и не назначенные в заявке. Только чтение: удаляет или оставляет сотрудник.

    Признак «создан ссылкой» косвенный (отдельного флага нет): список — для просмотра владельцем, не для автоматических
    действий.
    """
    rows: dict[int, dict] = {}
    links = (
        DocumentLink.objects.exclude(contact__isnull=True)
        .select_related("contact__company")
        .order_by("created_at", "pk")
    )
    for link in links:
        contact = link.contact
        if contact.pk in rows:
            rows[contact.pk]["links"] += 1
            continue
        if (
            contact.created_by_id is None
            and not contact.can_act
            and not contact.is_admin
            and not contact.is_primary
            and not contact.phone
            and contact.telegram_user_id is None
            and contact.created_at <= link.created_at <= contact.created_at + timedelta(minutes=1)
            and (link.recipient_email or "").lower() == (contact.email or "").lower()
        ):
            rows[contact.pk] = {
                "contact_id": contact.pk,
                "company_id": contact.company_id,
                "company": contact.company.name,
                "email": contact.email,
                "created_at": contact.created_at,
                "invited_at": contact.invited_at,
                "last_login_at": contact.last_login_at,
                "archived": contact.is_archived,
                "links": 1,
            }
    deal_contacts = set()
    for row in rows.values():
        row["assigned_in_deal"] = False
    if rows:
        from crm.models import Deal

        deal_contacts = set(Deal.objects.filter(contact_id__in=rows).values_list("contact_id", flat=True))
        for pk in deal_contacts:
            rows[pk]["assigned_in_deal"] = True
    return [row for row in rows.values() if not row["assigned_in_deal"]]
