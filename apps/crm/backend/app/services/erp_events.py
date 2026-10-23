"""Обработка событий ERP, принятых с шины rt_bus (M3-CRM-04 → B4, CONTRACTS §3/§9, ADR-0022).

Приёмник — `POST /bus/v1/events` (библиотека rt_bus: подпись, окно, inbox, идемпотентность по id,
`skipped` для неизвестных типов). Обработчики `uz.railtech.erp.*.v1` (`app.bus.handlers`) вызывают
`ErpEventsService.apply` в транзакции записи inbox: зеркало сделки, индекс документов, лента лида.
Сообщения Telegram здесь только считаются и кладутся в `erp_event_notices`; уходят они после коммита
(`app.bus.notices`), поэтому откат или автоповтор обработчика не задваивает сообщения.

Ошибки обработки (клиента нет, чужая компания, сбой БД) — исключение: шина повторит обработку
через 30 с, 2 мин, 10 мин и затем пометит запись `failed` — её видно в центре внешних сервисов.
Код акцепта (`quote.acceptance_code_requested`) — отдельный inline-обработчик: в inbox и журнал он
не попадает (шина хранит маску), в очередь не уходит, в логах его нет.
"""

from datetime import datetime
from decimal import Decimal

import structlog
from pydantic import ValidationError
from rt_bus import Event
from rt_contracts.events.erp import RequestCreatedV1
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.bus.erp_event import ErpEvent, parse_erp_event, plain
from app.bus.notices import ErpEventNotices
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead, LeadNote
from app.repositories import events
from app.security.audit import Actor
from app.services import deals as deals_service
from app.services.erp_acceptance_code import AcceptanceCodeDelivery
from app.services.erp_bot_messages import (
    client_message,
    feed_note,
    pick_language,
    staff_alert,
)
from app.services.erp_event_handlers import aware, dispatch
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

#: События, чьё сообщение клиенту описывает ТЕКУЩЕЕ состояние (срок, статус поставки, стадия):
#: устаревшим они в бот не уходят — только в ленту. Разовые факты (КП, счёт, акт) доходят всегда.
STALE_SILENT_EVENTS = frozenset(
    {"delivery.status_changed", "delivery.eta_changed", "deal.stage_changed"}
)


class ErpEventError(Exception):
    """Событие ERP не применено: шина повторит обработку, затем пометит запись `failed`."""


def _deal_amount(amount: str | None) -> Decimal | None:
    """Сумма сделки из события: None — КП клиенту ещё не отправлялось (контракт событий, FIX-29)."""
    return Decimal(amount) if amount is not None else None


def _is_fresh(deal: Deal, occurred_at: datetime) -> bool:
    """Событие применяется к зеркалу, если не старее уже применённого (порядок по `occurred_at`).

    Равное время применяется: у двух событий одного мгновения порядок прихода и есть порядок.
    """
    return deal.external_stage_at is None or aware(occurred_at) >= deal.external_stage_at


def _staff_target(deal: Deal | None, client: Client, lead: Lead | None) -> int | None:
    """Кому уходит служебное уведомление: ответственный за сделку, клиента или лида."""
    candidates = (
        deal.owner_user_id if deal else None,
        client.owner_user_id,
        lead.assigned_user_id if lead else None,
    )
    return next((int(user_id) for user_id in candidates if user_id), None)


class ErpEventsService:
    def __init__(
        self,
        settings_service: SettingsService,
        notices: ErpEventNotices,
        acceptance_code: AcceptanceCodeDelivery,
    ) -> None:
        self._settings_service = settings_service
        self._notices = notices
        self._acceptance_code = acceptance_code

    async def deliver_code(self, event: Event) -> str:
        """Код акцепта контакту в Telegram — из памяти запроса приёмника, мимо БД и очереди."""
        try:
            parsed = parse_erp_event(event)
        except (ValidationError, ValueError):
            # Текст ошибки pydantic несёт входные значения (в них код): наружу — только факт.
            raise ErpEventError("invalid acceptance code event") from None
        return await self._acceptance_code.deliver(event.id, parsed)

    async def apply(self, session: AsyncSession, event: Event) -> bool:
        """Применить событие ERP в транзакции `session`: зеркало, документы, лента; сообщения —
        в `erp_event_notices`. Возвращает, изменилось ли что-то (клиент найден и событие принято).
        """
        try:
            env = parse_erp_event(event)
        except (ValidationError, ValueError) as exc:
            raise ErpEventError(f"invalid {event.type}: {type(exc).__name__}") from None

        client = await session.get(Client, env.crm_client_id)
        if client is None:
            logger.warning(
                "erp_event_client_not_found", event_id=event.id, client_id=env.crm_client_id
            )
            raise ErpEventError(f"Client #{env.crm_client_id} not found")

        if client.erp_company_id is None:
            # Передача ещё идёт (ответ ERP не записан): сопоставление берём из подписанного
            # события — `crm_client_id` в нём ERP взяла из сопоставления, созданного нашей же
            # передачей. Ждать нельзя: при сбое передачи событие зависло бы навсегда.
            client.erp_company_id = env.erp_company_id
            await bus_events.client_updated(session, client, Actor.system(), ["erp_company_id"])
        elif client.erp_company_id != env.erp_company_id:
            logger.warning("erp_event_company_mismatch", event_id=event.id, client_id=client.id)
            raise ErpEventError(
                f"company mismatch: client #{client.id} is erp company "
                f"#{client.erp_company_id}, event carries #{env.erp_company_id}"
            )

        lead = await session.scalar(
            select(Lead).where(Lead.client_id == client.id).order_by(Lead.id.desc()).limit(1)
        )

        deal: Deal | None = None
        fresh = True
        env_deal = env.deal
        if env_deal is not None:
            deal, created = await self._mirror(session, client, lead, env)
            fresh = created or _is_fresh(deal, env.occurred_at)
            if fresh:
                deal.external_stage = str(plain(env_deal.stage))
                deal.external_stage_at = aware(env.occurred_at)
                deal.title = env_deal.title
                if env_deal.amount is not None:
                    deal.amount = Decimal(str(plain(env_deal.amount)))
                deal.currency = str(plain(env_deal.currency))
                if deal.client_id is None:
                    deal.client_id = client.id
            else:
                logger.info(
                    "erp_event_stale",
                    event_id=event.id,
                    event_type=env.event,
                    occurred_at=env.occurred_at.isoformat(),
                )

        # Устаревшее событие стадию, название и сумму зеркала не меняет (они возвращаются после
        # обработчика), но итог сделки (`won`/`lost`) применяется, а в ленту событие пишется.
        mirror = (deal.external_stage, deal.title, deal.amount, deal.currency) if deal else None
        note_text = await dispatch(session, env, client, deal)
        if deal is not None and not fresh and mirror is not None:
            deal.external_stage, deal.title, deal.amount, deal.currency = mirror
        cfg = await self._settings_service.get()
        deal_title = env_deal.title if env_deal else (deal.title if deal else "—")
        body = env.payload.model_dump(mode="json", by_alias=True)
        bot_msg = client_message(
            env.event,
            body,
            deal_title=deal_title,
            texts=cfg.texts,
            language=pick_language(lead.language if lead else None),
            cabinet_url=cfg.company.cabinet_url,
        )
        if note_text is None:
            # Приёмка и замечания по строкам поставки: текст ленты — из настроек (FIX-37).
            note_text = feed_note(
                env.event,
                body,
                contact_name=env.actor.name,
                deal_title=deal_title,
                texts=cfg.texts,
            )
        staff_alert_text = staff_alert(
            env.event,
            body,
            client_name=client.name,
            deal_title=deal_title,
            texts=cfg.texts,
        )

        if lead is not None and note_text:
            session.add(
                LeadNote(lead_id=lead.id, user_id=None, text=note_text, visible_to_bot=False)
            )
            lead.notes_count = (lead.notes_count or 0) + 1
            await events.publish(session, "lead.updated", lead_id=lead.id)

        # Сообщения не отправляются внутри транзакции: откат или повтор обработчика не должен
        # задваивать их. Они записываются в `erp_event_notices` и уходят после коммита.
        notices: list[dict[str, object]] = []
        if bot_msg and not (not fresh and env.event in STALE_SILENT_EVENTS):
            notices.append(
                {
                    "kind": "client",
                    "client_id": client.id,
                    "text": bot_msg.text,
                    "buttons": [list(button) for button in bot_msg.buttons],
                }
            )
        if staff_alert_text:
            target_user_id = _staff_target(deal, client, lead)
            if target_user_id:
                notices.append(
                    {"kind": "staff", "user_id": target_user_id, "text": staff_alert_text}
                )
        if notices:
            self._notices.add(session, event.id, notices)
        return True

    async def _mirror(
        self,
        session: AsyncSession,
        client: Client,
        lead: Lead | None,
        env: ErpEvent,
    ) -> tuple[Deal, bool]:
        """Зеркало сделки ERP: найти по `erp_deal_id`, иначе занять сделку лида или создать.

        Уникальный `deals.erp_deal_id` — последний рубеж: если параллельно то же зеркало создала
        передача клиента (`erp_handoff._mirror_request`), вставка в savepoint упадёт, и мы берём
        созданное — зеркало остаётся одно, каким бы порядком ни пришли ответ ERP и событие.
        Возвращает (сделка, создана ли новая).
        """
        env_deal = env.deal
        if env_deal is None:
            raise ValueError("event has no deal")
        erp_deal_id = env_deal.erp_deal_id
        found = await self._find_mirror(session, erp_deal_id)
        if found is not None:
            return found, False

        # Заявка передачи (`source=crm`) — уже существующая сделка лида: второй не заводим.
        adopt: Deal | None = None
        if (
            lead is not None
            and isinstance(env.data, RequestCreatedV1)
            and plain(env.data.payload.source) == "crm"
        ):
            adopt = await deals_service.open_deal(session, lead.id)
            if adopt is not None and adopt.erp_deal_id is not None:
                adopt = None
        try:
            async with session.begin_nested():
                if adopt is not None:
                    adopt.erp_deal_id = erp_deal_id
                    deal = adopt
                    created = False
                else:
                    amount = plain(env_deal.amount) if env_deal.amount is not None else None
                    deal = Deal(
                        client_id=client.id,
                        lead_id=lead.id if lead else None,
                        title=env_deal.title,
                        amount=_deal_amount(amount),
                        currency=str(plain(env_deal.currency)),
                        stage="open",
                        external_stage=str(plain(env_deal.stage)),
                        erp_deal_id=erp_deal_id,
                    )
                    session.add(deal)
                    created = True
                await session.flush()
        except IntegrityError:
            existing = await self._find_mirror(session, erp_deal_id)
            if existing is None:
                raise
            return existing, False
        return deal, created

    @staticmethod
    async def _find_mirror(session: AsyncSession, erp_deal_id: int) -> Deal | None:
        return await session.scalar(
            select(Deal).where(Deal.erp_deal_id == erp_deal_id).limit(1).with_for_update()
        )
