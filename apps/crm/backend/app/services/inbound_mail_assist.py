"""Помощник канцелярии (W18A-P2, B-INB-5): тип письма, суть и предложенное действие.

Модель — существующий алиас `qualifier-model` (классификация, под BudgetGuard, без резерва), читает
только отправителя, тему и текст (не вложения), текст письма — внутри XML-блока промпта
`prompts/mail_assist.md`. Ответ проверяет код (`domain/inbound_mail.parse_assist`): тип — только из
минимального набора, действие по типу выбирает код. Модель недоступна или ответ негодный —
`assist_status = unavailable`: карточка работает без подсказки. Подсказка ничего не делает сама.
Выключатель админа — «Помощник канцелярии» в карточке «Почта» (`integrations.imap.assist_enabled`,
как Q-019): выключен — `off`, модель не вызывается. Аудит — без текстов письма и ответа модели.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import prompts
from app.agents.llm import ChatCompleter, LlmUnavailableError
from app.domain.inbound_mail import AssistVerdict, parse_assist
from app.repositories import inbound_mail as repo
from app.security import audit
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

PROMPT = "mail_assist"
TEXT_CHARS = 6000
RESPONSE_FORMAT = {"type": "json_object"}


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

    async def suggest(self, mail_id: int) -> str:
        """Подсказка письму; итог — `done` | `unavailable` | `skip` (уже есть или письма нет)."""
        async with self._sessions() as session:
            row = await repo.get(session, mail_id)
        if row is None or row.assist_status != "pending":
            return "skip"
        mail = "\n".join(
            [
                f"От: {prompts.xml_escape(row.from_name)} <{prompts.xml_escape(row.from_email)}>",
                f"Тема: {prompts.xml_escape(row.subject)}",
                "",
                prompts.xml_escape(row.text[:TEXT_CHARS]),
            ]
        )
        cfg = await self._settings.get()
        if not cfg.integrations.imap.assist_enabled:
            return await self._save(mail_id, None, "off")
        verdict = None
        if self._model is not None:
            prompt = prompts.render(PROMPT, company=cfg.company.name, mail=mail)
            try:
                result = await self._model.complete(
                    [{"role": "user", "content": prompt}],
                    response_format=RESPONSE_FORMAT,
                    name="mail-assist",
                )
                verdict = parse_assist(result.text)
            except LlmUnavailableError:
                logger.warning("mail_assist_unavailable", mail_id=mail_id)
            except Exception:
                logger.exception("mail_assist_failed", mail_id=mail_id)
        return await self._save(mail_id, verdict, "done" if verdict else "unavailable")

    async def _save(self, mail_id: int, verdict: AssistVerdict | None, status: str) -> str:
        """Итог в строку письма и аудит (без текстов письма и ответа модели)."""
        async with self._sessions() as session, session.begin():
            row = await repo.get(session, mail_id, for_update=True)
            if row is None or row.assist_status != "pending":
                return "skip"
            row.assist_status = status
            if verdict is not None:
                row.assist_kind, row.assist_summary, row.assist_action = (
                    verdict.kind,
                    verdict.summary,
                    verdict.action,
                )
            await audit.record(
                session,
                audit.Actor.system(),
                "inbound_mail.assist",
                "inbound_mail",
                mail_id,
                after={"status": status, "kind": verdict.kind if verdict else None},
            )
        logger.info("mail_assist_saved", mail_id=mail_id, status=status)
        return status
