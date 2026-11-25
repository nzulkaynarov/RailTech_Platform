"""«Партнёр» из карточки лида (ЛП-1): лид оказался кандидатом в партнёры, а не клиентом.

Ответ «Партнёр» на вопрос «Кто это?» в карточке лида. Клиентский путь («Создать заявку») делает
лид клиентом и заводит заявку ERP; партнёрский — заявку кандидата в очередь «Заявки партнёров»
ERP (`source = lead`, `source_ref` = номер лида) и закрывает лид исходом «передан как партнёр»
(`discarded_kind = 'partner'`, `partner_application_id`): стадия `lost`, в `customer` лид не
попадает, из активных списков уходит — дальше его ведёт снабжение в ERP.

Порядок: сначала ERP (идемпотентно по номеру лида, повтор безопасен), затем одна транзакция CRM
под блокировкой лида. Сбой ERP — лид не тронут, действие можно повторить. Повтор после успеха
(двойной клик, параллельный запрос, вторая вкладка) — первый результат: ERP отдаёт ту же заявку,
CRM видит исход `partner` и ничего не меняет.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.contacts import partner_email
from app.domain.errors import ConflictError, InvalidTransitionError, Reason
from app.domain.stage_machine import decide
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.integrations.erp_partner import ErpPartnerClient, PartnerApplicationPayload
from app.models.leads import Lead
from app.repositories import events
from app.schemas.partner_handoff import PartnerHandoffIn, PartnerHandoffOut
from app.security import audit
from app.security.principal import Principal
from app.services import lead_parts
from app.services.leads import _lead, _move, _require_owner

logger = structlog.get_logger(__name__)

BackofficeModeProvider = Callable[[], Awaitable[BackofficeMode]]


def lead_number(lead_id: int) -> str:
    return f"L-{lead_id:04d}"


class PartnerHandoffService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        client: ErpPartnerClient,
        *,
        backoffice_mode: BackofficeModeProvider,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._mode = backoffice_mode

    async def hand_over(
        self, who: Principal, lead_id: int, body: PartnerHandoffIn
    ) -> PartnerHandoffOut:
        email = partner_email(body.email)
        async with self._sessions() as session:
            lead = await _lead(session, lead_id)
            await _require_owner(session, lead, who)
            done = _already(lead)
            if done is None:
                # Everything that could refuse is checked BEFORE the ERP call: after it the lead
                # must be closable, or an application without a closed lead is left behind.
                _require_closable(lead)
            language = lead.language
        if done is not None:
            return done
        if await self._mode() != BackofficeMode.ERP:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        result = await self._client.create_partner_application(
            PartnerApplicationPayload(
                crm_lead_id=lead_id,
                lead_number=lead_number(lead_id),
                company_name=body.company_name.strip(),
                categories_description=body.offer.strip(),
                contact_name=body.contact_name.strip(),
                country=body.country,
                inn=body.inn.strip(),
                kind=body.kind,
                email=email,
                phone=body.phone.strip(),
                language=language,
            )
        )
        async with self._sessions() as session, session.begin():
            lead = await _lead(session, lead_id)
            done = _already(lead)
            if done is not None:  # a parallel request closed the lead first
                return done
            _require_closable(lead)  # spam, a client or another outcome appeared meanwhile
            before = lead_parts.snapshot(lead)
            await _move(session, lead, Stage.LOST, who, "handed over as a partner")
            lead.discarded_kind = "partner"
            lead.partner_application_id = result.erp_application_id
            lead.owner_mode = OwnerMode.BOT.value
            lead.snoozed_until = None
            # An open deal stays: a partner hand-over is not a lost sale (summaries skip it).
            escalation = await lead_parts.active_escalation(session, lead_id)
            if escalation is not None:
                escalation.status, escalation.resolved_at = "closed", datetime.now(UTC)
                escalation.outcome = "handed_over_partner"
            await audit.record(
                session,
                who.actor,
                "lead.hand_over_partner",
                "lead",
                lead.id,
                before=before,
                after={
                    **lead_parts.snapshot(lead),
                    "partner_application_id": result.erp_application_id,
                },
            )
            await events.publish(
                session, "lead.updated", lead_id=lead.id, owner_mode=lead.owner_mode
            )
        logger.info(
            "lead_hand_over_partner", lead_id=lead_id, application_id=result.erp_application_id
        )
        return PartnerHandoffOut(
            lead_id=lead_id, application_id=result.erp_application_id, created=result.created
        )


def _require_closable(lead: Lead) -> None:
    """A client lead, a lead the stage machine cannot close or one already closed for another
    reason is not handed over as a partner."""
    if lead.client_id is not None or lead.discarded_kind is not None:
        raise InvalidTransitionError(
            "the lead is a client or closed", reason=Reason.REQUEST_NOT_ALLOWED
        )
    if not decide(Stage(lead.stage), Stage.LOST, TransitionSource.USER).allowed:
        raise InvalidTransitionError(
            f"a lead in stage {lead.stage} cannot be handed over", reason=Reason.REQUEST_NOT_ALLOWED
        )
    if lead.stage == Stage.LOST:
        raise InvalidTransitionError("the lead is closed", reason=Reason.REQUEST_NOT_ALLOWED)


def _already(lead: Lead) -> PartnerHandoffOut | None:
    if lead.discarded_kind == "partner" and lead.partner_application_id is not None:
        return PartnerHandoffOut(
            lead_id=lead.id, application_id=lead.partner_application_id, created=False
        )
    return None
