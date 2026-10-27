"""Перевод ответов CRM в модели «Ждут ответа» (D1-1): чистые функции без сети.

Словарь, а не решения: режим CRM `owner_mode` → `bot` / `waiting` / `manager`, номер `L-NNNN`,
сотрудник — `PersonRef`, вложение — ссылка BFF вместо ключа хранилища, служебная пометка причины
(`dialog: no_kb_match`) не уходит экрану. Коды причин, срока и роли подписывает экран.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any, get_args

from app.clients import crm_models as crm
from app.feeds.models import PersonRef
from app.feeds.numbers import lead_number
from app.schemas import initials_of
from app.schemas_crm_messages import (
    Author,
    ConversationCard,
    ConversationContacts,
    DecisionRole,
    HandoffFacts,
    HandoffInfo,
    HandoffNote,
    HandoffState,
    InboxGroup,
    Language,
    MessageInboxItem,
    OwnerMode,
    Priority,
    TeamNote,
    ThreadAttachment,
    ThreadMessage,
    Timeline,
)

API_PREFIX = "/api/v1"
_OWNER: dict[str, OwnerMode] = {"bot": "bot", "paused": "waiting", "human": "manager"}
_LANGUAGES: tuple[str, ...] = get_args(Language)
_PRIORITIES: tuple[str, ...] = get_args(Priority)
_STATES: tuple[str, ...] = get_args(HandoffState)
_AUTHORS: tuple[str, ...] = get_args(Author)
_TIMELINES: tuple[str, ...] = get_args(Timeline)
_ROLES: tuple[str, ...] = get_args(DecisionRole)
_CHANNEL = re.compile(r"^[a-z][a-z_]{0,15}$")
_REASON = re.compile(r"^[a-z_]{1,32}$")
# Служебная пометка CRM («dialog: no_kb_match», «qualifier: …») — не текст для сотрудника.
_SERVICE_NOTE = re.compile(r"^[a-z_]+:\s")

Names = Mapping[int, str]


def person(user_id: int | None, names: Names, fallback: str | None = None) -> PersonRef | None:
    if user_id is None:
        return None
    name = names.get(user_id) or fallback or f"#{user_id}"
    return PersonRef(id=str(user_id), name=name, initials=initials_of(name, name))


def language(value: str | None) -> Language:
    return value if value in _LANGUAGES else "ru"  # type: ignore[return-value]


def channel(value: str | None) -> str:
    return value if value and _CHANNEL.fullmatch(value) else "telegram"


def owner_mode(value: str) -> OwnerMode:
    return _OWNER.get(value, "bot")


def facts(raw: Mapping[str, Any] | crm.HandoffFacts | None, interest: list[str]) -> HandoffFacts:
    data: Mapping[str, Any] = (
        raw.model_dump() if isinstance(raw, crm.HandoffFacts) else dict(raw or {})
    )

    def text(key: str) -> str | None:
        value = data.get(key)
        return value.strip() or None if isinstance(value, str) else None

    timeline, role = data.get("timeline"), data.get("decision_role")
    return HandoffFacts(
        interest=interest,
        timeline=timeline if timeline in _TIMELINES else None,
        decision_role=role if role in _ROLES else None,
        budget_hint=text("budget_hint"),
        company=text("company"),
        company_size=text("company_size"),
        region=text("region"),
    )


def handoff(escalation: crm.EscalationOut | None, names: Names) -> HandoffInfo | None:
    if escalation is None or escalation.status not in _STATES:
        return None
    reason_text = escalation.reason_text
    if reason_text is not None and (not reason_text.strip() or _SERVICE_NOTE.match(reason_text)):
        reason_text = None
    return HandoffInfo(
        priority=escalation.priority if escalation.priority in _PRIORITIES else "info",
        state=escalation.status,
        reasons=[code for code in escalation.reason_codes if _REASON.fullmatch(code)],
        reason_text=reason_text,
        recommendation=escalation.recommendation,
        created_at=escalation.created_at,
        sla_due_at=escalation.sla_due_at,
        snoozed_until=escalation.snoozed_until,
        taken_by=person(escalation.taken_by_user_id, names),
    )


def note(lead: crm.LeadOut) -> HandoffNote:
    raw = lead.handoff_note
    interest = list(raw.facts.interest or []) if raw and raw.facts else []
    return HandoffNote(
        request=(raw.request if raw else None) or lead.need_summary,
        facts=facts(raw.facts if raw else None, interest),
        last_message=raw.last_lead_message if raw else None,
    )


def inbox_items(inbox: crm.InboxResponse, names: Names) -> list[MessageInboxItem]:
    """Лид — в первой подходящей группе: передача, мои, без менеджера."""
    seen: set[int] = set()
    items: list[MessageInboxItem] = []
    groups: Iterable[tuple[InboxGroup, list[crm.LeadOut]]] = (
        ("handoff", inbox.escalations),
        ("mine", inbox.mine),
        ("unassigned", inbox.unassigned),
    )
    for group, leads in groups:
        for lead in leads:
            if lead.id in seen:
                continue
            seen.add(lead.id)
            items.append(
                MessageInboxItem(
                    lead=lead_number(lead.id),
                    name=lead.display_name or lead_number(lead.id),
                    group=group,
                    language=language(lead.language),
                    channel=channel(lead.source),
                    unread=bool(lead.unread),
                    last_message_at=lead.last_lead_msg_at,
                    assigned=person(lead.assigned_user_id, names, lead.assigned_user_name),
                    handoff=handoff(lead.escalation, names),
                    note=note(lead),
                )
            )
    return items


def card(lead: crm.LeadDetail, names: Names, products: Mapping[str, str]) -> ConversationCard:
    interest = [products[k] for k in lead.product_interest if k in products and k != "company"]
    return ConversationCard(
        lead=lead_number(lead.id),
        name=lead.display_name or lead_number(lead.id),
        language=language(lead.language),
        channel=channel(lead.source),
        owner_mode=owner_mode(lead.owner_mode),
        assigned=person(lead.assigned_user_id, names, lead.assigned_user_name),
        consent_given_at=lead.consent_given_at,
        contacts=ConversationContacts(
            telegram=lead.tg_username,
            phone=lead.phone_e164 or lead.client_phone_e164,
            email=lead.email,
            company=lead.company_name,
        ),
        facts=facts(lead.qualification, interest),
        request=lead.need_summary,
        handoff=handoff(lead.escalation, names),
        client_in_erp=bool(lead.client_in_erp),
    )


def attachments(number: str, message_id: int, raw: list[dict[str, Any]]) -> list[ThreadAttachment]:
    """Вложения без ключа хранилища: имя, тип, размер и ссылка BFF на сохранённый файл."""
    out: list[ThreadAttachment] = []
    for index, item in enumerate(raw[:20]):
        stored = bool(item.get("stored")) and bool(item.get("storage_key"))
        size = item.get("size")
        out.append(
            ThreadAttachment(
                index=index,
                name=str(item.get("name") or "file"),
                mime=str(item.get("mime") or "application/octet-stream"),
                size=size if isinstance(size, int) and not isinstance(size, bool) else None,
                url=(
                    f"{API_PREFIX}/crm/messages/{number}/attachments/{message_id}/{index}"
                    if stored
                    else None
                ),
            )
        )
    return out


def thread_message(number: str, message: crm.MessageOut, names: Names) -> ThreadMessage:
    author = message.role if message.role in _AUTHORS else "system"
    name = names.get(message.sent_by_user_id) if message.sent_by_user_id is not None else None
    return ThreadMessage(
        id=message.id,
        author=author,
        author_name=name if author == "manager" else None,
        text=message.text,
        created_at=message.created_at,
        attachments=attachments(number, message.id, list(message.attachments)),
    )


def team_note(row: crm.NoteOut, names: Names) -> TeamNote:
    return TeamNote(
        id=row.id,
        author_name=names.get(row.user_id) if row.user_id is not None else None,
        text=row.text,
        created_at=row.created_at,
        visible_to_bot=row.visible_to_bot,
    )
