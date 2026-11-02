"""Помощник канцелярии (W18A-P2, B-INB-5): тип письма, суть и предложенное действие — по кнопке.

Решение юриста 2026-11-02: модель зовётся только по кнопке «Подсказать» в карточке письма (без неё
карточка работает вручную), в модель уходят отправитель, тема и текст — после маскирования
персональных данных кодом (`security/pii.mask_text`: e-mail, телефоны, ИНН, ПИНФЛ, карты и счета,
паспорт, дата рождения); вложения — никогда. Модель — существующий алиас `qualifier-model` под
BudgetGuard, без резерва; текст письма — внутри XML-блока промпта `prompts/mail_assist.md`. Ответ
проверяет код (`domain/inbound_mail.parse_assist`): тип — только из минимального набора, действие
по типу выбирает код; ничего не выполняется.

Журнал ИИ — аудит CRM без текстов: кто вызвал, функция, алиас, версия промпта, результат
(`ai.mail_assist`); решение человека по письму — `ai.mail_assist.decision` («принял предложенное»,
«выбрал другое», «вручную без ИИ», `decision_of`) и оценка трассы Langfuse. Выключатель админа —
«Помощник канцелярии» в карточке «Почта» (`integrations.imap.assist_enabled`, как Q-019).
"""

from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import prompts
from app.agents.llm import ChatCompleter, LlmUnavailableError
from app.domain.errors import ConflictError, NotFoundError, Reason
from app.domain.inbound_mail import AssistVerdict, parse_assist
from app.integrations import langfuse as lf
from app.models.inbound_mail import InboundMail
from app.repositories import inbound_mail as repo
from app.schemas.inbound_mail import InboundMailAssist as AssistOut
from app.security import audit
from app.security.pii import mask_text
from app.security.principal import Principal
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

PROMPT = "mail_assist"
FUNCTION = "mail_assist"
ALIAS = "qualifier-model"
TEXT_CHARS = 6000
RESPONSE_FORMAT = {"type": "json_object"}
Decision = Literal["accepted", "other", "manual"]


def masked_mail(row: InboundMail) -> str:
    """Что видит модель: отправитель, тема и текст без персональных данных; вложений нет."""
    lines = [
        f"От: {mask_text(row.from_name)} <{mask_text(row.from_email)}>",
        f"Тема: {mask_text(row.subject)}",
        "",
        mask_text(row.text[:TEXT_CHARS]),
    ]
    return prompts.xml_escape("\n".join(lines))


def decision_of(row: InboundMail, action: str) -> Decision:
    if row.assist_status != "done" or row.assist_action is None:
        return "manual"
    return "accepted" if row.assist_action == action else "other"


async def record_decision(
    session: AsyncSession, row: InboundMail, action: str, actor: audit.Actor
) -> Decision:
    """Решение человека по письму — в журнал ИИ (без текстов) и оценкой трассы Langfuse."""
    decision = decision_of(row, action)
    await audit.record(
        session,
        actor,
        "ai.mail_assist.decision",
        "inbound_mail",
        row.id,
        after={
            "function": FUNCTION,
            "decision": decision,
            "action": action,
            "suggested": row.assist_action,
            "trace_id": row.assist_trace_id,
        },
    )
    try:
        lf.score(row.assist_trace_id, "human_decision", decision, comment=action)
    except Exception:
        logger.warning("mail_assist_score_failed", mail_id=row.id, exc_info=True)
    return decision


def view(row: InboundMail, enabled: bool) -> AssistOut:
    """Подсказка для экрана; не запрашивали и помощник выключен — `off` (кнопки нет)."""
    status = "off" if row.assist_status == "none" and not enabled else row.assist_status
    return AssistOut.model_validate(
        {
            "status": status,
            "kind": row.assist_kind,
            "summary": row.assist_summary,
            "action": row.assist_action,
        }
    )


class InboundMailAssist:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        model: ChatCompleter | None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._model = model

    async def suggest(self, who: Principal, mail_id: int) -> AssistOut:
        """«Подсказать»: подсказка уже есть — она же, без второго вызова модели."""
        cfg = await self._settings.get()
        if not cfg.integrations.imap.assist_enabled:
            raise ConflictError("mail assist is disabled", reason=Reason.ASSIST_DISABLED)
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
        if row is None:
            raise NotFoundError("mail not found")
        if row.assist_status == "done":
            return view(row, True)
        if row.status != "new":
            raise ConflictError("mail is already handled", status=row.status)
        version = prompts.version(PROMPT)
        verdict, trace_id = await self._ask(who, cfg.company.name, masked_mail(row), version)
        return await self._save(who, mail_id, verdict, trace_id, version)

    async def _ask(
        self, who: Principal, company: str, mail: str, version: str
    ) -> tuple[AssistVerdict | None, str | None]:
        if self._model is None:
            return None, None
        prompt = prompts.render(PROMPT, company=company, mail=mail)
        with lf.ai_trace(
            "mail-assist", user_id=who.user_id, function=FUNCTION, version=version, input=mail
        ):
            trace_id = lf.current_trace_id()
            try:
                result = await self._model.complete(
                    [{"role": "user", "content": prompt}],
                    response_format=RESPONSE_FORMAT,
                    name="mail-assist",
                )
            except LlmUnavailableError:
                logger.warning("mail_assist_unavailable")
                return None, trace_id
            except Exception:
                logger.exception("mail_assist_failed")
                return None, trace_id
        return parse_assist(result.text), trace_id

    async def _save(
        self,
        who: Principal,
        mail_id: int,
        verdict: AssistVerdict | None,
        trace_id: str | None,
        version: str,
    ) -> AssistOut:
        status = "done" if verdict is not None else "unavailable"
        async with self._sessions() as session, session.begin():
            row = await repo.get(session, mail_id, for_update=True)
            if row is None:
                raise NotFoundError("mail not found")
            if row.assist_status != "done":
                row.assist_status = status
                row.assist_trace_id = trace_id
                if verdict is not None:
                    row.assist_kind = verdict.kind
                    row.assist_summary = verdict.summary
                    row.assist_action = verdict.action
            await audit.record(
                session,
                who.actor,
                "ai.mail_assist",
                "inbound_mail",
                mail_id,
                after={
                    "function": FUNCTION,
                    "alias": ALIAS,
                    "prompt_version": version,
                    "result": status,
                    "kind": verdict.kind if verdict else None,
                    "trace_id": trace_id,
                },
            )
            out = view(row, True)
        logger.info("mail_assist_saved", mail_id=mail_id, status=status)
        return out
