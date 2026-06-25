"""AI #4 — deal-chat reply assist.

In a deal's chat, a "Suggest reply" action drafts a professional reply DRAFT from
the recent message history + minimal deal context. The user ALWAYS reviews and
edits the draft in the message input before sending (the AI never auto-sends), so
this layer only has to be *useful*. Rule 1 (no hallucination): the draft is built
ONLY from the actual conversation in OUR DB — the system prompt forbids inventing
commitments, prices, dates or facts not present in the thread.

Reuses the proven Structured-Outputs client from `sourcing.services_ai` (single
Anthropic client, json_schema output, token-usage logging). Gated on
`settings.AI_IMPORT_ENABLED` → returns {"draft": ""} when off, so the chat UI flow
never 500s when the feature is disabled / no API key is configured.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from accounts.models import CustomUser

from ..models import Deal
from .messaging import user_can_access_deal_chat

logger = logging.getLogger(__name__)

# How many of the most-recent messages feed the model. Bounded so the prompt stays
# small (chat threads can be long) — the latest exchange is what a reply responds to.
RECENT_MESSAGES_LIMIT = 20

# Structured Outputs guarantee clean JSON (no "Конечно, вот ваш ответ…" preamble).
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "draft": {
            "type": "string",
            "description": "Черновик профессионального ответа на русском языке для отправки в чат сделки",
        }
    },
    "required": ["draft"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Ты — помощник менеджера B2B-площадки (железнодорожное и промышленное оборудование). "
    "На вход даётся недавняя переписка в чате одной сделки и краткий контекст сделки. "
    "Составь ОДИН вежливый, деловой ЧЕРНОВИК ответа на последнее сообщение собеседника — "
    "его автор отредактирует и отправит вручную.\n\n"
    "ПРАВИЛА:\n"
    "1. НИЧЕГО НЕ ВЫДУМЫВАЙ. Опирайся ТОЛЬКО на факты из переданной переписки и контекста. "
    "НЕ называй цены, сроки, объёмы, гарантии или обязательства, которых нет в диалоге. "
    "Если для ответа не хватает данных — вежливо уточни недостающее, а не придумывай.\n"
    "2. Пиши на русском, кратко и по делу (обычно 1–4 предложения), в деловом тоне.\n"
    "3. Не давай твёрдых коммерческих обещаний от лица компании — формулируй как намерение "
    "(«уточним и вернёмся», «подготовим предложение»), решение остаётся за человеком.\n"
    "4. Не повторяй дословно последнее сообщение и не добавляй служебных пометок — верни "
    "только сам текст ответа в поле draft.\n"
    "Верни результат строго по заданной JSON-схеме."
)


def _client():
    # Reuse the single, tested Anthropic client factory — one client, one config.
    from sourcing.services_ai import _client as ai_client

    return ai_client()


def _deal_context(deal: Deal) -> str:
    """Minimal, factual deal context for the prompt — title + counterparties only.

    Strictly from OUR DB; no derived claims. Keeps the model grounded on which deal
    it is replying within without leaking anything beyond what chat members see.
    """
    parts = [f"Сделка: {deal.title or f'#{deal.pk}'}"]
    if deal.company_id and getattr(deal, "company", None):
        parts.append(f"Компания-заказчик: {deal.company.name}")
    stage = getattr(deal, "stage", None)
    if stage is not None and getattr(stage, "name", ""):
        parts.append(f"Этап: {stage.name}")
    return "; ".join(parts)


def _format_history(messages, requesting_user: CustomUser) -> str:
    """Render the recent thread oldest→newest with role labels.

    `messages` arrives newest-first (sliced for the limit); we reverse so the model
    reads the conversation in natural order and replies to the LAST line.
    """
    lines = []
    for message in reversed(list(messages)):
        if message.message_type != "CHAT":
            # System/notification rows are not part of the human dialogue.
            continue
        who = "Вы" if message.sender_id == requesting_user.id else (message.sender.get_full_name() or "Собеседник")
        lines.append(f"{who}: {message.text}")
    return "\n".join(lines)


def suggest_chat_reply(deal_id: int, requesting_user: CustomUser) -> dict:
    """Draft a reply for the deal's chat from its recent history.

    Returns {"draft": str}. Empty draft ("") when AI is disabled, when the deal does
    not exist, when the user may NOT access this deal's chat (same visibility scoping
    the chat itself uses — `user_can_access_deal_chat`), or when there is no human
    conversation yet to reply to. NEVER raises into the request flow for these cases;
    a hard API/transport error from Claude propagates for the view to map to 5xx.
    """
    if not getattr(settings, "AI_IMPORT_ENABLED", False):
        return {"draft": ""}

    try:
        deal = Deal.objects.select_related("company", "stage").get(pk=deal_id)
    except Deal.DoesNotExist:
        return {"draft": ""}

    # Same deal-visibility scoping the chat uses — a user may only get a draft for a
    # deal whose chat they can access. No cross-tenant drafting.
    if not user_can_access_deal_chat(requesting_user, deal):
        return {"draft": ""}

    recent = list(
        deal.messages.filter(message_type="CHAT")
        .select_related("sender")
        .order_by("-timestamp")[:RECENT_MESSAGES_LIMIT]
    )
    history = _format_history(recent, requesting_user)
    if not history.strip():
        # Nothing to reply to yet — don't spend a paid call on an empty thread.
        return {"draft": ""}

    user_msg = (
        f"Контекст сделки: {_deal_context(deal)}\n\n"
        f"Недавняя переписка (старые → новые):\n{history}\n\n"
        "Составь черновик ответа на последнее сообщение собеседника."
    )

    client = _client()
    response = client.messages.create(
        model=settings.AI_IMPORT_MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_msg}]}],
        output_config={"format": {"type": "json_schema", "schema": REPLY_SCHEMA}},
    )

    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info(
            "AI chat-reply usage: deal=%s input=%s output=%s",
            deal_id,
            usage.input_tokens,
            usage.output_tokens,
        )
    if response.stop_reason == "refusal":
        logger.warning("AI chat-reply: model declined (%s)", getattr(response, "stop_details", None))
        return {"draft": ""}

    raw = next((block.text for block in response.content if block.type == "text"), "{}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AI chat-reply: unparseable JSON (len=%s)", len(raw or ""))
        return {"draft": ""}

    return {"draft": str(data.get("draft", "")).strip()}
