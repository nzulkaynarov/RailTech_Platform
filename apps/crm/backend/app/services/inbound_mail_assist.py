"""Помощник канцелярии (W18A-P2, B-INB-5): тип письма, суть и предложенное действие — по кнопке.

Решение юриста 2026-11-02: модель зовётся только по кнопке «Подсказать» в карточке письма (без неё
карточка работает вручную). В модель уходят домен отправителя (без имени и адреса), тема и текст —
после маскирования персональных данных кодом по политике из настройки `ai.pii_policy`
(`security/pii.mask_for_model`; PD-BIZ, решение владельца 2026-11-03): «Деловая» (по умолчанию)
скрывает паспорт, ПИНФЛ, номера карт и даты рождения, «Строгая» — ещё e-mail, телефоны, ИНН и счета;
политика читается при каждом вызове, перезапуск не нужен; вложения — никогда. Модель — существующий
алиас `qualifier-model` под BudgetGuard, без резерва; текст письма — внутри XML-блока промпта
`prompts/mail_assist.md`. Типы письма модель берёт из справочника «Типы входящих писем»
(действующие, не хардкод, MAIL-TYPES); ответ проверяет код (`domain/mail_types.parse_verdict`):
тип — только из действующих, иначе пусто; правило отправителя побеждает ИИ, человек подтверждает
или меняет тип. Ничего не выполняется.

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
from app.domain.mail_types import ActiveType, TypeVerdict, parse_verdict, types_block
from app.integrations import langfuse as lf
from app.models.inbound_mail import InboundMail
from app.repositories import inbound_mail as repo
from app.repositories import mail_types as types_repo
from app.schemas.inbound_mail import InboundMailAssist as AssistOut
from app.security import audit
from app.security.pii import DEFAULT_POLICY, PiiPolicy, mask_for_model
from app.security.principal import Principal
from app.services import mail_types as types_service
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

PROMPT = "mail_assist"
FUNCTION = "mail_assist"
ALIAS = "qualifier-model"
TEXT_CHARS = 6000
RESPONSE_FORMAT = {"type": "json_object"}
_LEGACY_KINDS = ("buyer", "official", "supplier_doc", "other")
Decision = Literal["accepted", "other", "manual"]


def masked_mail(row: InboundMail, policy: PiiPolicy = DEFAULT_POLICY) -> str:
    """Что видит модель: домен отправителя (без имени и адреса), тема и текст без персональных
    данных по политике; вложений нет."""
    domain = row.from_email.rpartition("@")[2]
    lines = [
        f"От: домен {domain or 'неизвестен'}",
        f"Тема: {mask_for_model(row.subject, policy)}",
        "",
        mask_for_model(row.text[:TEXT_CHARS], policy),
    ]
    return prompts.xml_escape("\n".join(lines))


#: Подсказки до MAIL-TYPES хранили действие тремя короткими словами.
_LEGACY_ACTIONS = {
    "register": "register_incoming",
    "lead": "create_lead",
    "archive": "archive_mailing",
}


def decision_of(row: InboundMail, action: str) -> Decision:
    """Принял ли человек подсказку: действие совпало с действием типа, который предложил ИИ."""
    suggested = _LEGACY_ACTIONS.get(row.assist_action or "", row.assist_action)
    if row.assist_status != "done" or suggested is None:
        return "manual"
    return "accepted" if suggested == action else "other"


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
    # `kind` и `action` — устаревшие поля контракта: только у подсказок до MAIL-TYPES, новые —
    # `type` письма.
    kind = row.assist_kind if row.assist_kind in _LEGACY_KINDS else None
    action = row.assist_action if row.assist_action in _LEGACY_ACTIONS else None
    return AssistOut.model_validate(
        {"status": status, "kind": kind, "summary": row.assist_summary, "action": action}
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
        if row.status not in ("new", "in_work"):
            raise ConflictError("mail is already handled", status=row.status)
        version = prompts.version(PROMPT)
        async with self._sessions() as session:
            types = await types_service.active_types(session)
        verdict, trace_id = await self._ask(
            who, cfg.company.name, masked_mail(row, cfg.ai.pii_policy), types, version
        )
        return await self._save(who, mail_id, verdict, trace_id, version)

    async def _ask(
        self,
        who: Principal,
        company: str,
        mail: str,
        types: list[ActiveType],
        version: str,
    ) -> tuple[TypeVerdict | None, str | None]:
        if self._model is None:
            return None, None
        block = prompts.xml_escape(types_block(types))
        prompt = prompts.render(PROMPT, company=company, mail=mail, types=block)
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
        verdict, problem = parse_verdict(result.text, types)
        if problem is not None:  # причина словом-кодом, без текста письма и ответа модели
            logger.warning("mail_assist_unparsed", reason=problem, version=version)
        return verdict, trace_id

    async def _save(
        self,
        who: Principal,
        mail_id: int,
        verdict: TypeVerdict | None,
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
                    row.assist_summary = verdict.summary
                    await self._apply_type(session, row, verdict)
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
                    "type": verdict.type_code if verdict else None,
                    "trace_id": trace_id,
                },
            )
            out = view(row, True)
        logger.info("mail_assist_saved", mail_id=mail_id, status=status)
        return out

    @staticmethod
    async def _apply_type(session: AsyncSession, row: InboundMail, verdict: TypeVerdict) -> None:
        """Тип от помощника — только если его ещё не задали правило отправителя или человек: они
        сильнее."""
        row.assist_kind = None  # устаревшее поле: тип письма — `type_code`
        found = await types_repo.get_type(session, verdict.type_code) if verdict.type_code else None
        row.assist_action = found.default_action if found is not None else None
        if found is not None and found.active and row.type_source in (None, "ai"):
            row.type_code, row.type_source = found.code, "ai"
