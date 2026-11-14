"""Помощник письма (план 1.4): «Подготовить текст» и «Перевести на английский» — модель только предлагает.

Черновик и перевод модель пишет в Markdown, мост `rt_docs.markdown_to_body` (план 1.3) делает из него тело документа по
контракту `documents/body.schema.json`. Перевод приходит вместе с обратным переводом на русский: сотрудник проверяет
смысл, не зная языка. Ничего не сохраняется в документ — тело вставляет человек. Вызовы — шлюз ИИ по алиасу
`draft-model`, журнал вызовов и расход — `ai_suggestions` (как у разбора входящего).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Final

import structlog
from rt_docs import body_to_markdown, markdown_to_body, normalize_body
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.ai import gateway
from app.config import Settings
from app.errors import conflict, invalid_fields
from app.models import AiSuggestion, Employee
from app.schemas.ai import LetterAssistIn, LetterAssistSuggestion
from app.services.letter_intake import _spent_today

log = structlog.get_logger(__name__)

DRAFT: Final = "letter_draft"
TRANSLATE: Final = "letter_translate"
MAX_TOKENS: Final = 4000
MAX_SOURCE: Final = 20000
SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["markdown", "back_translation"],
    "properties": {
        "markdown": {"type": "string"},
        "back_translation": {"type": ["string", "null"]},
    },
}
_LANG_NAMES = {"ru": "ru", "uz": "uz", "en": "en"}


def _user_text(data: LetterAssistIn, current: str) -> str:
    if data.action == "translate":
        return f"<lang>{data.lang}</lang>\n<letter>\n{current}\n</letter>"
    parts = [f"<lang>{data.lang}</lang>", f"<brief>\n{(data.brief or '').strip()}\n</brief>"]
    if data.recipient:
        parts.append(f"<recipient>{data.recipient.strip()}</recipient>")
    if data.subject:
        parts.append(f"<subject>{data.subject.strip()}</subject>")
    if current:
        parts.append(f"<current>\n{current}\n</current>")
    return "\n".join(parts)


async def suggest(
    session: AsyncSession, settings: Settings, employee: Employee, data: LetterAssistIn
) -> LetterAssistSuggestion:
    """Черновик или перевод тела письма. Вызов модели — вне транзакции, журнал — своей транзакцией."""
    current = body_to_markdown(normalize_body(data.body)).strip() if data.body else ""
    if data.action == "translate" and not current.strip():
        raise invalid_fields("Сначала напишите текст письма.", body="required")
    if data.action == "draft" and not (data.brief or "").strip():
        raise invalid_fields("Напишите, о чём письмо.", brief="required")
    if len(current) > MAX_SOURCE:
        raise invalid_fields("Письмо слишком длинное для помощника.", body="too_long")
    if not gateway.available(settings):
        raise conflict("ai_unavailable", "Помощник не настроен — напишите текст сами.")
    async with session.begin():
        spent = await _spent_today(session)
    budget = Decimal(str(settings.ai_daily_budget_usd))
    if budget > 0 and spent >= budget:
        raise conflict("ai_budget_exceeded", "Дневной лимит помощника исчерпан — напишите текст сами.")

    function = TRANSLATE if data.action == "translate" else DRAFT
    prompt = gateway.load_prompt(function)
    suggestion_id = uuid.uuid4()
    body = gateway.body_for(
        function=function,
        prompt=prompt,
        user_content=[{"type": "text", "text": _user_text(data, current)}],
        schema=SCHEMA,
        max_tokens=MAX_TOKENS,
        user_id=employee.crm_user_id,
        session_id=str(suggestion_id),
    )
    result = await gateway.call_json(settings, body)
    markdown = str((result.data or {}).get("markdown") or "").strip() if result.status == "ok" else ""
    back = (result.data or {}).get("back_translation") if result.status == "ok" else None
    status = "empty" if result.status == "ok" and not markdown else result.status
    async with session.begin():
        session.add(
            AiSuggestion(
                id=suggestion_id,
                function=function,
                alias=gateway.FUNCTION_ALIASES[function],
                prompt_version=prompt.version,
                source="text",
                status=status,
                error_code=result.error_code or None,
                crm_user_id=employee.crm_user_id,
                created_at=clock.now(),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
            )
        )
    log.info("ai.letter_assist", suggestion_id=str(suggestion_id), action=data.action, status=status)
    if result.status == "budget":
        raise conflict("ai_budget_exceeded", "Дневной лимит помощника исчерпан — напишите текст сами.")
    if not markdown:
        raise conflict("ai_unavailable", "Помощник сейчас не ответил — напишите текст сами или повторите позже.")
    imported = markdown_to_body(markdown, lang=data.lang)
    return LetterAssistSuggestion(
        suggestion_id=suggestion_id,
        body=imported.body,
        back_translation=str(back).strip() or None if back else None,
        alias=gateway.FUNCTION_ALIASES[function],
        prompt_version=prompt.version,
    )
