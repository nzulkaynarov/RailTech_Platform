"""Deep-link `/start` бота: метка источника, заявка кабинета, подписанная ссылка на запрос с сайта
(D1-9).

Раньше параметр после `/start` терялся: `/start web` и `/start deal_<id>` здоровались как с чужим.
Разбор —
`domain/start_link.py`; здесь применение после того, как `ConversationService.start` завёл лида и
ответил:

* `web` — новый лид получает источник `web` («пришёл с сайта»); у существующего ничего не меняется;
* `deal_<id>` — привязка к заявке только если этот Telegram уже привязан и проверен как клиент и
  заявка принадлежит
  именно этому клиенту; иначе — обычное приветствие и запись в аудит (чужую заявку подставить
  нельзя: ссылку
  кабинета может написать кто угодно);
* `lead_<…>` — подписанная ссылка из письма-подтверждения, выданная системой: Telegram-карточка
  склеивается с
  запросом с сайта (одноразово: если у запроса уже есть Telegram, ссылка не срабатывает).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import client_texts
from app.domain.start_link import StartLink, parse_start_payload, verify_lead_link
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote, TelegramIdentity
from app.repositories import events
from app.repositories import leads as repo
from app.security import audit
from app.services.lead_merge import merge_with_lead

logger = structlog.get_logger(__name__)

__all__ = ["StartLinkResult", "StartLinkService"]


@dataclass(frozen=True, slots=True)
class StartLinkResult:
    """Дополнительные сообщения бота после приветствия (на языке лида)."""

    texts: list[str] = field(default_factory=list)


class StartLinkService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], key: bytes) -> None:
        self._sessions = sessions
        self._key = key

    async def apply(
        self, tg_user_id: int, payload: str | None, now: datetime | None = None
    ) -> StartLinkResult:
        link = parse_start_payload(payload)
        if link.kind in ("none", "unknown"):
            return StartLinkResult()
        moment = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            identity = await repo.get_identity(session, tg_user_id)
            if identity is None or identity.lead_id is None:
                return StartLinkResult()
            lead = await repo.get_lead(session, identity.lead_id, for_update=True)
            if lead is None or lead.erased_at is not None:
                return StartLinkResult()
            if link.kind == "web":
                return await self._web(session, lead)
            if link.kind == "deal":
                return await self._deal(session, lead, identity, link)
            return await self._lead(session, lead, identity, link, moment)

    async def _web(self, session: AsyncSession, lead: Lead) -> StartLinkResult:
        """Метка источника: только у только что созданного лида (без истории)."""
        if lead.source == "telegram" and lead.last_lead_msg_at is None and lead.notes_count == 0:
            lead.source = "web"
            await audit.record(
                session,
                audit.Actor.system(),
                "lead.start_web",
                "lead",
                lead.id,
                after={"source": "web"},
            )
            await events.publish(session, "lead.updated", lead_id=lead.id)
        return StartLinkResult()

    async def _deal(
        self, session: AsyncSession, lead: Lead, identity: TelegramIdentity, link: StartLink
    ) -> StartLinkResult:
        deal = None
        if identity.client_id is not None and identity.verified_at is not None and link.deal_id:
            deal = await session.scalar(
                select(Deal).where(
                    Deal.erp_deal_id == link.deal_id, Deal.client_id == identity.client_id
                )
            )
        if deal is None:
            await audit.record(
                session,
                audit.Actor.system(),
                "lead.start_deal_rejected",
                "lead",
                lead.id,
                after={"reason": "not_the_clients_request"},
            )
            logger.info("start_deal_rejected", lead_id=lead.id)
            return StartLinkResult()
        session.add(
            LeadNote(
                lead_id=lead.id,
                user_id=None,
                text=f"Клиент открыл бота из кабинета по заявке «{deal.title}».",
                visible_to_bot=False,
            )
        )
        lead.notes_count += 1
        await events.publish(session, "lead.updated", lead_id=lead.id)
        return StartLinkResult([client_texts.start_deal(lead.language, deal.title)])

    async def _lead(
        self,
        session: AsyncSession,
        lead: Lead,
        identity: TelegramIdentity,
        link: StartLink,
        moment: datetime,
    ) -> StartLinkResult:
        target_id = verify_lead_link(self._key, link.raw or "", moment)
        stale = StartLinkResult([client_texts.start_link_stale(lead.language)])
        if target_id is None:
            logger.info("start_lead_link_invalid", lead_id=lead.id)
            return stale
        if target_id == lead.id:
            return StartLinkResult([client_texts.start_lead_bound(lead.language)])
        target = await repo.get_lead(session, target_id)
        taken = await session.scalar(
            select(TelegramIdentity.id).where(TelegramIdentity.lead_id == target_id).limit(1)
        )
        if target is None or target.erased_at is not None or taken is not None or lead.client_id:
            return stale  # одноразово: у запроса уже есть Telegram; клиента к запросу не приклеить
        outcome = await merge_with_lead(session, identity, target_id)
        if outcome is None:
            return stale
        await audit.record(
            session,
            audit.Actor.system(),
            "lead.start_link_bound",
            "lead",
            outcome.survivor_id,
            after={"absorbed": outcome.absorbed_id},
        )
        survivor = await repo.get_lead(session, outcome.survivor_id)
        language = survivor.language if survivor is not None else lead.language
        return StartLinkResult([client_texts.start_lead_bound(language)])
