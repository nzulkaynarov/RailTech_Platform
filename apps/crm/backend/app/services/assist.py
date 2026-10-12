"""ИИ-помощь менеджеру при ответе (Q-019): «Черновик» и «Улучшить» — только по кнопке.

Ничего не отправляется клиенту: сервис возвращает текст в поле ответа CRM. Право — как у
ответа (ответственный за лида или админ, лид у человека). Модель — алиас `dialog-model`
под BudgetGuard; каждый вызов учитывается в `llm_usage` на лида и пишется в аудит (без
текстов). Факты проверяет код: в черновике нет чисел не из базы знаний и переписки, в
«Улучшить» — нет новых чисел (`app/domain/assist.py`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import prompts
from app.agents.llm import ChatCompleter, LlmUnavailableError
from app.domain.assist import improve_adds_numbers, may_assist, strip_unsupported
from app.domain.budget import Route
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.domain.stages import OwnerMode
from app.integrations.llm_usage import lead_scope
from app.repositories import leads as repo
from app.schemas.settings import AppSettings
from app.security import audit
from app.security.principal import Principal
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

Mode = Literal["draft", "improve"]
Notice = Literal["numbers_removed", "new_numbers"]
ALIAS = "dialog-model"


@dataclass(frozen=True, slots=True)
class LeadSnapshot:
    owner_mode: str
    assigned_user_id: int | None
    language: str
    messages: list[tuple[str, str]]  # (role, text), старые → новые


@dataclass(frozen=True, slots=True)
class AssistResult:
    text: str
    cost_usd: float | None
    notice: Notice | None = None


class AssistStore(Protocol):
    async def load(self, lead_id: int, history: int) -> LeadSnapshot | None: ...

    async def audit(self, who: Principal, lead_id: int, after: dict[str, Any]) -> None: ...


class KbSearcher(Protocol):
    async def fragments(self, query: str, top_k: int, language: str) -> list[tuple[str, str]]: ...


class RouteGuard(Protocol):
    async def route(self, alias: str, *, allows_fallback: bool) -> Route: ...


class AssistService:
    def __init__(
        self,
        settings: SettingsService,
        store: AssistStore,
        kb: KbSearcher,
        models: Mapping[Mode, ChatCompleter],
        guard: RouteGuard | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._kb = kb
        self._models = models
        self._guard = guard

    async def assist(
        self, who: Principal, lead_id: int, mode: Mode, text: str | None
    ) -> AssistResult:
        cfg = await self._settings.get()
        if not cfg.bot.assist_enabled:
            raise ConflictError("AI assist is disabled", reason=Reason.ASSIST_DISABLED)
        source = (text or "").strip()
        if mode == "improve" and not 0 < len(source) <= cfg.bot.assist_max_input_chars:
            raise ValidationFailedError("text is empty or too long", field="text")
        lead = _check_access(await self._store.load(lead_id, cfg.bot.history_messages), who)
        if await self._over_limit():
            raise ConflictError("model spend limit reached", reason=Reason.ASSIST_BUDGET)
        with lead_scope(lead_id):
            if mode == "draft":
                result = await self._draft(cfg, lead)
            else:
                result = await self._improve(source, lead.language)
        await self._store.audit(
            who,
            lead_id,
            {
                "mode": mode,
                "input_chars": len(source),
                "output_chars": len(result.text),
                "notice": result.notice,
            },
        )
        logger.info("lead_assist", lead_id=lead_id, mode=mode, notice=result.notice)
        if not result.text:
            raise ConflictError("draft had only unsupported facts", reason=Reason.ASSIST_EMPTY)
        return result

    async def _over_limit(self) -> bool:
        if self._guard is None:
            return False
        return await self._guard.route(ALIAS, allows_fallback=True) is Route.UNAVAILABLE

    async def _draft(self, cfg: AppSettings, lead: LeadSnapshot) -> AssistResult:
        last = next((t for role, t in reversed(lead.messages) if role == "lead" and t), None)
        if last is None:
            raise ConflictError("no client message to answer", reason=Reason.ASSIST_NO_HISTORY)
        fragments = await self._kb.fragments(last, cfg.kb.top_k, lead.language)
        prompt = prompts.render(
            "assist_draft",
            company=cfg.company.name,
            language_name=prompts.LANGUAGE_NAMES.get(lead.language, "русский"),
            max_words=str(cfg.bot.max_words),
            kb=prompts.xml_items("fragment", [({"title": t}, body) for t, body in fragments]),
            history=prompts.xml_items("message", [({"role": r}, t) for r, t in lead.messages]),
        )
        user = "Подготовь черновик ответа менеджера на последнее сообщение клиента."
        reply, cost = await self._complete("draft", prompt, user)
        sources = [body for _, body in fragments] + [t for _, t in lead.messages]
        check = strip_unsupported(reply, sources)
        notice: Notice | None = "numbers_removed" if check.removed else None
        return AssistResult(text=check.text, cost_usd=cost, notice=notice)

    async def _improve(self, source: str, language: str) -> AssistResult:
        prompt = prompts.render(
            "assist_improve",
            language_name=prompts.LANGUAGE_NAMES.get(language, "русский"),
            text=prompts.xml_escape(source),
        )
        user = "Отредактируй текст из блока <manager_text>."
        improved, cost = await self._complete("improve", prompt, user)
        if not improved or improve_adds_numbers(source, improved):
            return AssistResult(text=source, cost_usd=cost, notice="new_numbers")
        return AssistResult(text=improved, cost_usd=cost)

    async def _complete(self, mode: Mode, system: str, user: str) -> tuple[str, float | None]:
        messages: Sequence[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            result = await self._models[mode].complete(messages, name=f"assist_{mode}")
        except LlmUnavailableError as exc:
            raise UpstreamUnavailableError(
                "model unavailable", reason=Reason.ASSIST_UNAVAILABLE
            ) from exc
        return result.text.strip(), result.cost_usd


def _check_access(lead: LeadSnapshot | None, who: Principal) -> LeadSnapshot:
    if lead is None:
        raise NotFoundError("lead not found")
    if lead.owner_mode != OwnerMode.HUMAN:
        raise ConflictError("take the lead before replying", reason=Reason.TAKE_FIRST)
    if not may_assist(
        assigned_user_id=lead.assigned_user_id, user_id=who.user_id, is_admin=who.is_admin
    ):
        raise ForbiddenError(
            "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
        )
    return lead


class DbAssistStore:
    """Лид и переписка из БД; запись `lead.assist` в аудит (длины, не тексты)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, lead_id: int, history: int) -> LeadSnapshot | None:
        async with self._sessions() as session:
            lead = await repo.get_lead(session, lead_id)
            if lead is None or lead.erased_at is not None:
                return None
            rows = await repo.recent_messages(session, lead_id, history)
            return LeadSnapshot(
                owner_mode=lead.owner_mode,
                assigned_user_id=lead.assigned_user_id,
                language=lead.language,
                messages=[(m.role, m.text) for m in rows if m.text],
            )

    async def audit(self, who: Principal, lead_id: int, after: dict[str, Any]) -> None:
        async with self._sessions() as session, session.begin():
            await audit.record(session, who.actor, "lead.assist", "lead", lead_id, after=after)


class KbFragments:
    """Фрагменты базы знаний тем же гибридным поиском, что у бота; сбой поиска — без KB."""

    def __init__(self, search: Any) -> None:
        self._search = search

    async def fragments(self, query: str, top_k: int, language: str) -> list[tuple[str, str]]:
        try:
            found = await self._search.search(query, top_k=top_k, language=language)
        except Exception as exc:  # noqa: BLE001 — черновик без KB лучше, чем отказ
            logger.warning("assist_kb_failed", error=type(exc).__name__)
            return []
        return [(hit.document_title, hit.content) for hit in found.hits]
