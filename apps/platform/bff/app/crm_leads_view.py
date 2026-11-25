"""Перевод ответов CRM в модели «Клиенты · Лиды» (W16-D1-2b): чистые функции без сети.

Вкладка и область списка → параметры CRM `GET /leads`; лид → строка и карточка (статус Платформы
CRM-02, просрочка и открытая передача по эскалации, последние сообщения, подтверждение заявки,
срок первого ответа и приглашение — D1-9). Словарь, а не решения.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, get_args

from app.clients import crm_models as crm
from app.crm_messages_view import Names, channel, facts, handoff, language, person
from app.feeds.numbers import lead_number
from app.schemas_crm_leads import (
    ClientInvitation,
    ClientShort,
    ConsentMethod,
    EmailProblem,
    InviteChannel,
    LeadCard,
    LeadConsent,
    LeadFirstResponse,
    LeadMessagePreview,
    LeadNotice,
    LeadOrigin,
    LeadPlatformStatus,
    LeadRow,
    LeadScope,
    LeadTab,
)
from app.schemas_crm_messages import Author, ConversationContacts
from app.schemas_do_not_work import DoNotWork

_STATUSES: tuple[str, ...] = get_args(LeadPlatformStatus)
_AUTHORS: tuple[str, ...] = get_args(Author)
_CONSENT: tuple[str, ...] = get_args(ConsentMethod)
_INVITE: tuple[str, ...] = get_args(InviteChannel)
_CLIENT_STAGES = frozenset({"customer", "won"})
LAST_MESSAGES = 5


def list_params(
    tab: LeadTab,
    scope: LeadScope,
    q: str | None,
    source: str | None,
    offset: int,
    limit: int,
    sort: str | None = None,
) -> dict[str, Any]:
    """Параметры CRM `GET /leads`: вкладка — `platform_status`, «мои» — `owner=me`, «просроченные» —
    `overdue=true`, канал — `source`, порядок (`field` / `-field`) — `sort` и `order` CRM."""
    params: dict[str, Any] = {"offset": offset, "limit": limit}
    if tab != "all":
        params["platform_status"] = tab
    if scope == "mine":
        params["owner"] = "me"
    elif scope == "overdue":
        params["overdue"] = "true"
    if q and q.strip():
        params["q"] = q.strip()
    if source:
        params["source"] = source
    if sort:
        params["sort"] = sort.removeprefix("-")
        params["order"] = "desc" if sort.startswith("-") else "asc"
    return params


def status_of(platform_status: str | None, stage: str) -> LeadPlatformStatus:
    """Статус CRM-02; CRM без него (старая версия) — грубо по стадии."""
    if platform_status in _STATUSES:
        return platform_status  # type: ignore[return-value]
    if stage == "new":
        return "new"
    if stage in _CLIENT_STAGES:
        return "client"
    if stage == "lost":
        return "lost"
    return "dialog"


def _handoff_open(escalation: crm.EscalationOut | None) -> bool:
    return escalation is not None and escalation.status in ("open", "snoozed")


def _overdue(escalation: crm.EscalationOut | None, now: datetime) -> bool:
    return (
        escalation is not None
        and escalation.status == "open"
        and escalation.sla_due_at is not None
        and escalation.sla_due_at < now
    )


def lead_row(lead: crm.LeadOut, names: Names, now: datetime) -> LeadRow:
    return LeadRow(
        lead=lead_number(lead.id),
        name=lead.display_name or lead_number(lead.id),
        status=status_of(_status_value(lead.platform_status), lead.stage),
        channel=channel(lead.source),
        language=language(lead.language),
        assigned=person(lead.assigned_user_id, names, lead.assigned_user_name),
        need=lead.need_summary,
        last_message_at=lead.last_lead_msg_at,
        unread=bool(lead.unread),
        handoff_open=_handoff_open(lead.escalation),
        overdue=_overdue(lead.escalation, now),
        client_id=lead.client_id,
    )


def _status_value(value: Any) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def _channel_value(value: Any) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) and raw != "none" else None


def notice(raw: crm.NoticeOut | None) -> LeadNotice | None:
    if raw is None:
        return None
    return LeadNotice(
        channel=_channel_value(raw.channel),
        status=raw.status.value,
        sent_at=raw.sent_at,
        error_text=raw.error_text,
    )


def email_problem(raw: crm.EmailUndeliverableOut | None) -> EmailProblem | None:
    """Letters to the address come back (delivery reports): reason code and the last report date."""
    if raw is None:
        return None
    return EmailProblem(reason=raw.reason.value, at=raw.last_at)


def invitation(raw: crm.InvitationOut | None) -> ClientInvitation | None:
    return invitation_of(raw) if raw is not None else None


def invitation_of(raw: crm.InvitationOut) -> ClientInvitation:
    """Приглашение в кабинет; канал `none` CRM — без канала."""
    suggested = _channel_value(raw.suggested_channel)
    return ClientInvitation(
        status=raw.status.value,
        channel=_channel_value(raw.channel),
        sent_via=[v.value for v in raw.sent_via or []],
        sent_at=raw.sent_at,
        contact_name=raw.contact_name,
        error_text=raw.error_text,
        available_channels=[v.value for v in raw.available_channels or []],
        suggested_channel=suggested if suggested in _INVITE else None,
        can_resend=bool(raw.can_resend),
    )


def preview(message: crm.MessageOut) -> LeadMessagePreview:
    author = message.role if message.role in _AUTHORS else "system"
    return LeadMessagePreview(
        author=author,
        text=message.text,
        at=message.created_at,
    )


def lead_card(
    lead: crm.LeadDetail,
    names: Names,
    products: Mapping[str, str],
    messages: list[crm.MessageOut],
    client: ClientShort | None,
) -> LeadCard:
    interest = [products[k] for k in lead.product_interest if k in products and k != "company"]
    method = lead.consent_method if lead.consent_method in _CONSENT else None
    return LeadCard(
        lead=lead_number(lead.id),
        name=lead.display_name or lead_number(lead.id),
        status=status_of(_status_value(lead.platform_status), lead.stage),
        channel=channel(lead.source),
        language=language(lead.language),
        assigned=person(lead.assigned_user_id, names, lead.assigned_user_name),
        contacts=ConversationContacts(
            telegram=lead.tg_username,
            phone=lead.phone_e164 or lead.client_phone_e164,
            email=lead.email,
            company=lead.company_name,
        ),
        reply_via=channel(lead.reply_via) if lead.reply_via else None,
        reply_blocked=lead.reply_blocked,
        consent=LeadConsent(given_at=lead.consent_given_at, method=method),
        facts=facts(lead.qualification, interest),
        need=lead.need_summary,
        interest=interest,
        handoff=handoff(lead.escalation, names),
        last_messages=[preview(m) for m in messages[-LAST_MESSAGES:]],
        client=client,
        confirmation=notice(lead.confirmation),
        first_response=LeadFirstResponse(
            due_at=lead.first_response_due_at, overdue=bool(lead.first_response_overdue)
        ),
        invitation=invitation(lead.invitation),
        email_problem=email_problem(lead.email_undeliverable),
        origin=origin_of(lead.origin),
        discarded=_discarded(lead.discarded_kind),
        duplicate_of=lead_number(lead.duplicate_of_lead_id) if lead.duplicate_of_lead_id else None,
        partner_application=lead.partner_application_id,
    )


def _discarded(kind: Any) -> Literal["spam", "test", "duplicate"] | None:
    value = _status_value(kind)
    return value if value in ("spam", "test", "duplicate") else None  # type: ignore[return-value]


def origin_of(raw: crm.LeadOriginOut | None) -> LeadOrigin | None:
    if raw is None:
        return None
    utm = raw.utm or {}
    lang = raw.landing_language
    return LeadOrigin(
        form=raw.form,
        page=raw.page,
        referrer=raw.referrer,
        campaign=utm.get("utm_campaign"),
        utm_source=utm.get("utm_source"),
        utm_medium=utm.get("utm_medium"),
        language=lang if lang in ("ru", "uz", "en") else None,
    )


def client_short(raw: Any, lead: crm.LeadDetail) -> ClientShort | None:
    """Клиент лида: из `GET /clients/{id}`; CRM не ответила — имя компании лида."""
    if lead.client_id is None:
        return None
    if isinstance(raw, dict) and isinstance(raw.get("name"), str):
        inn = raw.get("inn")
        mark = raw.get("do_not_work")
        return ClientShort(
            id=lead.client_id,
            name=raw["name"],
            inn=inn if isinstance(inn, str) else None,
            do_not_work=DoNotWork.model_validate(mark) if isinstance(mark, dict) else None,
        )
    if lead.company_name:
        return ClientShort(id=lead.client_id, name=lead.company_name, inn=None)
    return None
