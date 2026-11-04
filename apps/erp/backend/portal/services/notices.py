"""Колокольчик кабинета и маршрутизатор внешнего канала (NOTIFY-2, ADR-0023 п. 2; ADR-0008 — канал по контакту).

Любое событие для контрагента → строка ленты на каждый действующий контакт компании (колокольчик — всегда). Внешний канал —
один на событие и контакт (`choose_channel`):

* событие не важное — только колокольчик;
* бот CRM сам шлёт клиенту это событие (`NoticeKind.bot_sends`), компания сопоставлена клиенту CRM и у контакта привязан
  Telegram — бот, ERP не дублирует (до переноса бота на маршрутизатор после пилота);
* письмо уже ушло процессом документа (КП по каналам ERP-11) — второго не шлём;
* иначе — письмо на адрес контакта (сразу или, у ответа менеджера в чате, через задержку — если не прочитано и контакт не
  заходил); адреса нет — только колокольчик.

Вид, который бот не шлёт (просрочка оплаты, ответ менеджера, возврат карточки партнёра), контакту с Telegram уходит письмом:
уведомление не теряется. Письмо — шаблон `portal_notice` на языке контакта, с подвалом «Настроить уведомления»; отправка —
задача `portal.send_notice_email` после коммита и сборщик `portal.send_due_notice_emails` (отложенные и недошедшие),
идемпотентно по строке. Таблица видов, групп и каналов — `docs/systems/erp/notifications.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from parties.models import Contact, active_contact_q

from ..models import NoticeChannel, NoticeEmailState, PortalNotice
from .access import company_has_cabinet_access

logger = logging.getLogger(__name__)

#: Ответ менеджера в чате: письмо, только если за это время уведомление не прочитали (Intercom, Slack).
MANAGER_REPLY_EMAIL_DELAY = timedelta(minutes=10)
#: Паузы перед повтором письма после сбоя передачи; попыток — на одну больше, потом строка `failed` с причиной.
EMAIL_RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=30))
MAX_EMAIL_ATTEMPTS = len(EMAIL_RETRY_DELAYS) + 1


@dataclass(frozen=True)
class NoticeKind:
    code: str
    group: str
    object_type: str
    action: str
    #: Модуль кабинета, которому открыт объект: без него уведомление не видно в ленте и не считается в бейдже.
    module: str
    #: Важное — внешний канал сразу; прочее — только колокольчик.
    important: bool
    #: Бот CRM сам шлёт клиенту это событие ERP (`erp_bot_messages.client_message`) — ERP не дублирует в Telegram.
    bot_sends: bool
    email_delay: Optional[timedelta] = None


#: Виды уведомлений; тот же перечень — `NotificationKind` контракта `erp-portal.yaml` (сверка — тест).
KINDS: dict[str, NoticeKind] = {
    kind.code: kind
    for kind in (
        NoticeKind("quote_sent", "documents", "quote", "awaiting_decision", "quotes", True, True),
        NoticeKind("invoice_issued", "money", "invoice", "issued", "invoices", True, True),
        NoticeKind("payment_overdue", "money", "invoice", "overdue", "invoices", True, False),
        NoticeKind("act_issued", "documents", "act", "awaiting_acceptance", "acts", True, True),
        NoticeKind("delivery_status_changed", "deliveries", "delivery", "status_changed", "deliveries", False, True),
        NoticeKind("delivery_eta_changed", "deliveries", "delivery", "eta_changed", "deliveries", True, True),
        NoticeKind(
            "manager_replied", "messages", "chat", "replied", "messages", True, False, MANAGER_REPLY_EMAIL_DELAY
        ),
        NoticeKind(
            "partner_card_returned", "partner_products", "partner_product", "returned", "my_products", True, False
        ),
    )
}

GROUPS = ("documents", "money", "deliveries", "messages", "partner_products")


def visible_kinds(modules: Iterable[str]) -> list[str]:
    """Виды, чей объект открыт модулям сессии."""
    enabled = set(modules)
    return [code for code, kind in KINDS.items() if kind.module in enabled]


def _normalized(email: str | None) -> str:
    return (email or "").strip().lower()


#: Почему контакту не пишем письмо (поле `PortalNotice.email_reason`).
REASON_NOT_INVITED = "not_invited"
REASON_INVALID_EMAIL = "invalid_email"
REASON_NO_EMAIL = "no_email"


def email_allowed(contact: Contact, document_contact_ids: Iterable[int] = ()) -> Optional[str]:
    """Можно ли писать контакту письмо-уведомление; `None` — можно, иначе причина.

    Решение лида по ревью #402 (Odoo portal — письмо подписчикам документа, HubSpot — контактам с доступом к порталу):
    письмо получает контакт документа (контакт сделки, получатель КП) и контакт, которого пригласили в кабинет или который
    уже входил. Неприглашённому первым письмом должно прийти приглашение (ADR-0023 п. 3) — до него только колокольчик.
    Неверный адрес отсекается здесь, а не на передаче почте.
    """
    email = (contact.email or "").strip()
    if not email:
        return REASON_NO_EMAIL
    try:
        validate_email(email)
    except ValidationError:
        return REASON_INVALID_EMAIL
    if contact.pk in set(document_contact_ids) or contact.invited_at or contact.last_login_at:
        return None
    return REASON_NOT_INVITED


def choose_channel(
    kind: NoticeKind,
    contact: Contact,
    *,
    bot_reaches: bool,
    already_emailed: set[str],
    document_contact_ids: Iterable[int] = (),
) -> tuple[str, str]:
    """Внешний канал уведомления для контакта — один на событие (ADR-0023 п. 2) — и причина, если письма нет."""
    if not kind.important:
        return NoticeChannel.CABINET, ""
    if kind.bot_sends and bot_reaches and contact.telegram_user_id:
        return NoticeChannel.TELEGRAM, ""
    if _normalized(contact.email) in already_emailed:
        return NoticeChannel.SOURCE, ""
    reason = email_allowed(contact, document_contact_ids)
    if reason:
        return NoticeChannel.CABINET, reason
    return (NoticeChannel.EMAIL_DELAYED if kind.email_delay else NoticeChannel.EMAIL), ""


def crm_bot_reaches(company_id: int) -> bool:
    """События компании доходят до бота CRM, только если она сопоставлена клиенту CRM (иначе события нет)."""
    from integration.models import CrmClientMapping

    return CrmClientMapping.objects.filter(company_id=company_id).exists()


def notify(
    kind_code: str,
    *,
    company,
    object_id: int,
    object_number: str = "",
    params: Optional[dict] = None,
    link: str,
    dedup: str,
    bot_reaches: Optional[bool] = None,
    already_emailed: Iterable[str] = (),
    document_contact_ids: Iterable[int] = (),
) -> list[PortalNotice]:
    """Записать событие в ленту каждого действующего контакта компании и выбрать каждому внешний канал.

    Идемпотентно: повтор того же события (`dedup`) строк и писем не добавляет. Вызывать в транзакции изменения: откат —
    ни строк, ни писем (письма уходят после коммита). Компании, закрытой для кабинета, уведомлять некуда — пусто.
    """
    kind = KINDS[kind_code]
    if company is None or not company_has_cabinet_access(company.pk):
        return []
    if bot_reaches is None:
        bot_reaches = crm_bot_reaches(company.pk)
    emailed = {_normalized(email) for email in already_emailed if email}
    emailed.discard("")
    document_contacts = {pk for pk in document_contact_ids if pk}
    text_params = {key: "" if value is None else str(value) for key, value in (params or {}).items()}
    now = timezone.now()
    created: list[PortalNotice] = []
    contacts = Contact.objects.filter(active_contact_q(), company_id=company.pk).order_by("pk")
    for contact in contacts:
        channel, reason = choose_channel(
            kind, contact, bot_reaches=bot_reaches, already_emailed=emailed, document_contact_ids=document_contacts
        )
        wants_email = channel in (NoticeChannel.EMAIL, NoticeChannel.EMAIL_DELAYED)
        notice, was_created = PortalNotice.objects.get_or_create(
            contact=contact,
            dedup_key=f"{kind.code}:{dedup}"[:200],
            defaults={
                "company_id": company.pk,
                "kind": kind.code,
                "group": kind.group,
                "object_type": kind.object_type,
                "object_id": int(object_id),
                "object_number": (object_number or "")[:100],
                "action": kind.action,
                "text_key": kind.code,
                "params": text_params,
                "link": link,
                "channel": channel,
                "email_state": NoticeEmailState.PENDING if wants_email else NoticeEmailState.NONE,
                "email_due_at": (now + (kind.email_delay or timedelta(0))) if wants_email else None,
                "email_reason": reason,
            },
        )
        if was_created:
            created.append(notice)
    immediate = [n.pk for n in created if n.channel == NoticeChannel.EMAIL]
    if immediate:
        transaction.on_commit(lambda: _enqueue_emails(immediate))
    return created


def _enqueue_emails(notice_ids: list[int]) -> None:
    from portal.tasks import send_notice_email

    for notice_id in notice_ids:
        try:
            send_notice_email.delay(notice_id)
        except (
            Exception
        ):  # noqa: BLE001 — брокер лёг: письмо дошлёт сборщик `send_due_notice_emails`, операция не падает
            logger.exception("portal notice #%s: письмо не поставлено в очередь, дошлёт сборщик", notice_id)


# ── Лента контакта ──────────────────────────────────────────────────────────────────────────────────────────────────


def contact_notices(contact, company, modules: Iterable[str]):
    """Уведомления контакта сессии в её компании, видимые её модулям."""
    return PortalNotice.objects.filter(contact=contact, company=company, kind__in=visible_kinds(modules))


def unread_count(contact, company, modules: Iterable[str]) -> int:
    return contact_notices(contact, company, modules).filter(read_at__isnull=True).count()


def page(contact, company, modules: Iterable[str], *, before_id: Optional[int], limit: int) -> tuple[list, bool]:
    """Страница ленты по убыванию `id`; второе — есть ли более ранние."""
    rows = contact_notices(contact, company, modules)
    if before_id:
        rows = rows.filter(pk__lt=before_id)
    items = list(rows.order_by("-pk")[: limit + 1])
    return items[:limit], len(items) > limit


def mark_read(contact, company, modules: Iterable[str], *, ids: Optional[list[int]] = None, all: bool = False) -> int:
    """Прочитать свои уведомления (по `ids` или все видимые); чужие `id` не трогаются. Прочтение гасит отложенное письмо.

    Возвращает число непрочитанных после отметки.
    """
    rows = contact_notices(contact, company, modules).filter(read_at__isnull=True)
    if not all:
        rows = rows.filter(pk__in=list(ids or []))
    now = timezone.now()
    with transaction.atomic():
        rows.filter(email_state=NoticeEmailState.PENDING).update(
            email_state=NoticeEmailState.CANCELLED, email_reason="read"
        )
        rows.update(read_at=now)
    return unread_count(contact, company, modules)


# ── Письмо по уведомлению ───────────────────────────────────────────────────────────────────────────────────────────


def cabinet_url() -> str:
    return getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")


#: Якорь раздела «Уведомления» профиля (NOTIFY-1) — подвал писем контрагенту.
NOTIFICATION_SETTINGS_PATH = "/profile#notifications"


def contact_was_present(notice: PortalNotice) -> bool:
    """Контакт заходил в кабинет после уведомления — письмо об ответе менеджера не нужно (ADR-0023 п. 2).

    Присутствие — вход в кабинет после уведомления (`Contact.last_login_at`); отметку чата (`last_seen` ленты сообщений)
    добавляет часть «ответ менеджера» после слияния CHAT-1.
    """
    last_login = notice.contact.last_login_at
    return bool(last_login and last_login >= notice.created_at)


def deliver_email(notice_id: int) -> str:
    """Отправить письмо по уведомлению, если оно ещё нужно. Идемпотентно: строка блокируется, отправленное не повторяется.

    Итог: `sent`; `cancelled` (прочитано, контакт заходил, адреса нет, кабинет закрыт); `retry` (почта не приняла письмо —
    повтор после паузы `EMAIL_RETRY_DELAYS`); `failed` (попытки исчерпаны — строка больше не берётся, причина в
    `email_reason`); `not_due` (рано); `skipped` (нечего отправлять — уже отправлено, отменено или не отправлено).
    """
    from notifications.emails import send_templated_email
    from notifications.models import EmailLog

    now = timezone.now()
    with transaction.atomic():
        notice = (
            PortalNotice.objects.select_for_update(of=("self",))
            .select_related("contact", "company")
            .filter(pk=notice_id, email_state=NoticeEmailState.PENDING)
            .first()
        )
        if notice is None:
            return "skipped"
        if notice.email_due_at and notice.email_due_at > now:
            return "not_due"
        contact = notice.contact
        reason = None
        if notice.read_at is not None:
            reason = "read"
        elif KINDS[notice.kind].email_delay and contact_was_present(notice):
            reason = "present"
        elif contact.archived_at is not None or contact.company_id != notice.company_id:
            reason = "no_recipient"
        elif not company_has_cabinet_access(notice.company_id):
            reason = "no_cabinet"
        else:
            reason = email_allowed(contact, (contact.pk,))  # адрес мог смениться после уведомления
        if reason:
            notice.email_state = NoticeEmailState.CANCELLED
            notice.email_reason = reason
            notice.save(update_fields=["email_state", "email_reason"])
            logger.info("portal notice #%s: письмо отменено (%s)", notice.pk, reason)
            return "cancelled"
        log = send_templated_email(
            "portal_notice",
            email_context(notice),
            to=[contact.email],
            language=contact.language,
            purpose=f"portal_notice.{notice.kind}",
            fail_silently=True,  # сбой передачи — попытка строки, а не исключение: сборщик идёт дальше
        )
        if log is not None and log.status == EmailLog.STATUS_FAILED:
            return _attempt_failed(notice, log.error or "send_failed", now)
        notice.email_state = NoticeEmailState.SENT
        notice.email_sent_at = now
        notice.email_attempts += 1
        notice.email_reason = ""
        notice.save(update_fields=["email_state", "email_sent_at", "email_attempts", "email_reason"])
    return "sent"


def _attempt_failed(notice: PortalNotice, error: str, now) -> str:
    """Неудачная попытка: пауза перед повтором или, когда попытки исчерпаны, конечное `failed` с причиной."""
    notice.email_attempts += 1
    notice.email_reason = str(error)[:255]
    if notice.email_attempts >= MAX_EMAIL_ATTEMPTS:
        notice.email_state = NoticeEmailState.FAILED
        logger.warning(
            "portal notice #%s: письмо не отправлено, попытки исчерпаны (%s)", notice.pk, notice.email_reason
        )
        result = "failed"
    else:
        notice.email_due_at = now + EMAIL_RETRY_DELAYS[notice.email_attempts - 1]
        logger.warning("portal notice #%s: письмо не принято, повтор в %s", notice.pk, notice.email_due_at)
        result = "retry"
    notice.save(update_fields=["email_attempts", "email_reason", "email_state", "email_due_at"])
    return result


def _record_crash(notice_id: int, error: Exception) -> str:
    """Непредвиденный сбой строки (база, шаблон): попытка засчитывается отдельной транзакцией, сборщик не встаёт."""
    with transaction.atomic():
        notice = (
            PortalNotice.objects.select_for_update(of=("self",))
            .filter(pk=notice_id, email_state=NoticeEmailState.PENDING)
            .first()
        )
        if notice is None:
            return "skipped"
        # Только имя класса: текст исключения может нести адрес, данные письма или секрет — в базу и журнал он не идёт.
        return _attempt_failed(notice, error.__class__.__name__, timezone.now())


def _email_money(amount: Optional[str], currency: Optional[str]) -> str:
    """Сумма письма — тем же форматом, что в PDF и письме КП (разряды неразрывным пробелом, код валюты)."""
    if not amount:
        return ""
    from crm.templatetags.document_format import money

    return money(Decimal(amount), currency or "UZS")


def _email_date(value: Optional[str]) -> str:
    """ISO-дата параметра → ДД.ММ.ГГГГ, как в письмах ERP; пусто — пусто."""
    if not value:
        return ""
    try:
        return date.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def email_context(notice: PortalNotice) -> dict:
    """Контекст шаблона `portal_notice`: вид, параметры текста, ссылка на объект и на настройки уведомлений."""
    from parties.models import Company

    from notifications.emails import email_brand

    from .access import _own_company_id

    base = cabinet_url()
    own_id = _own_company_id()
    # Бренд письма — своя компания (продавец), как в письмах КП; не настроена — заголовок платформы.
    seller = Company.objects.filter(pk=own_id).first() if own_id else None
    params = notice.params or {}
    return {
        "kind": notice.kind,
        "contact_name": notice.contact.name,
        "company_name": notice.company.name,
        "number": params.get("number") or notice.object_number,
        "amount": _email_money(params.get("amount"), params.get("currency")),
        "due_date": _email_date(params.get("due_date")),
        "deal": params.get("deal", ""),
        "eta": _email_date(params.get("eta")),
        "previous_eta": _email_date(params.get("previous_eta")),
        "reason": params.get("reason", ""),
        "reminder": bool(params.get("reminder")),
        "open_url": f"{base}{notice.link}",
        "settings_url": f"{base}{NOTIFICATION_SETTINGS_PATH}",
        **email_brand(seller),
    }


def send_due_emails(limit: int = 200) -> dict:
    """Сборщик: письма, чей срок наступил (отложенные, повторы после сбоя и не поставленные в очередь после коммита).

    Сбой одной строки не останавливает остальные: попытка засчитывается строке (пауза, затем `failed`), цикл идёт дальше.
    """
    due = list(
        PortalNotice.objects.filter(email_state=NoticeEmailState.PENDING, email_due_at__lte=timezone.now())
        .order_by("email_due_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    result = {"sent": 0, "cancelled": 0, "skipped": 0, "not_due": 0, "retry": 0, "failed": 0}
    for notice_id in due:
        try:
            outcome = deliver_email(notice_id)
        except SoftTimeLimitExceeded:
            raise  # время задачи вышло — не сбой строки: попытку не засчитываем, остальное доберёт следующий запуск
        except Exception as error:  # noqa: BLE001 — сбой строки не должен вечно держать очередь писем всех компаний
            logger.error("portal notice #%s: сбой отправки письма (%s)", notice_id, error.__class__.__name__)
            outcome = _record_crash(notice_id, error)
        result[outcome] += 1
    return result
