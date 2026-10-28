"""Обработчики событий, которые CRM принимает с шины (`POST /bus/v1/events`).

* события ERP (`erp_types()`: все `uz.railtech.erp.*.v1`, кроме кода акцепта и типов для EDS —
  `NOT_FOR_CRM`) — в очереди Procrastinate, в транзакции записи inbox: зеркало сделки, документы,
  лента лида, сообщения Telegram (`ErpEventsService.apply`);
* `uz.railtech.erp.quote.acceptance_code_requested.v1` — inline, прямо в запросе приёмника: код
  акцепта не пишется в inbox (там маска), не уходит в очередь и не попадает в логи;
* `uz.railtech.erp.invite.requested.v1` — inline: бот присылает контакту приглашение в кабинет, итог
  записывается в `client_notices` (D1-9);
* `uz.railtech.{erp,eds}.mail.requested.v1` — в очереди, в транзакции inbox: письмо, которое ERP или
  EDS просят отправить, — строка журнала доставки; отправка — задачей после коммита (W18A-P1).

Типы без обработчика и версии выше поддерживаемой шина записывает как `skipped` и отвечает 200.
Импорт модуля регистрирует обработчики в реестре `rt_bus` по умолчанию.
"""

from rt_bus import Event, subscribe
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_event import CODE_TYPE, INVITE_TYPE, erp_types
from app.bus.runtime import current_container
from app.services.mail_requests import MAIL_REQUEST_TYPES


async def on_erp_event(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.apply(session, event)


@subscribe(CODE_TYPE, inline=True)
async def on_acceptance_code(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.deliver_code(event)


@subscribe(INVITE_TYPE, inline=True)
async def on_invite_requested(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.deliver_invite(event)


for _event_type in erp_types():
    subscribe(_event_type)(on_erp_event)


async def on_mail_requested(event: Event, session: AsyncSession) -> None:
    await current_container().mail_requests.accept(session, event)


for _mail_type in MAIL_REQUEST_TYPES:
    subscribe(_mail_type)(on_mail_requested)
