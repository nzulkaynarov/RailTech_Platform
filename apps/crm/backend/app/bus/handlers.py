"""Обработчики событий, которые CRM принимает с шины (`POST /bus/v1/events`).

* события ERP (`erp_types()`: все `uz.railtech.erp.*.v1`, кроме кода акцепта и типов для EDS —
  `NOT_FOR_CRM`) — в очереди Procrastinate, в транзакции записи inbox: зеркало сделки, документы,
  лента лида, сообщения Telegram (`ErpEventsService.apply`);
* `uz.railtech.erp.quote.acceptance_code_requested.v1` — inline, прямо в запросе приёмника: код
  акцепта не пишется в inbox (там маска), не уходит в очередь и не попадает в логи;
* `uz.railtech.erp.invite.requested.v1` — inline: бот присылает контакту приглашение в кабинет, итог
  записывается в `client_notices` (D1-9);
* `uz.railtech.{erp,eds}.mail.requested.v1` — в очереди, в транзакции inbox: письмо, которое ERP или
  EDS просят отправить, — строка журнала доставки; отправка — задачей после коммита (W18A-P1);
* `uz.railtech.erp.partner.client_requested.v1` — в очереди, в транзакции inbox: партнёр
  приглашён в кабинет — CRM находит или создаёт клиента и контакты и отвечает
  `crm.partner.client_resolved` (PART-CRM); `erp.partner.client_rejected` снимает привязку;
* `uz.railtech.eds.notice.requested.v1` — в очереди, в транзакции inbox: уведомление сотрудникам по
  поручениям входящих (P8b) — строка колокольчика и сообщение Telegram после коммита;
* `uz.railtech.erp.contact.telegram_test_requested.v1` — inline: проверочное сообщение контакту в
  его привязанный Telegram (NOTIFY-1);
* `uz.railtech.erp.contact.telegram_unlink_requested.v1` — в очереди, в транзакции inbox: контакт
  отключил
  Telegram в кабинете — CRM отвязывает и публикует `contact.updated` (NOTIFY-1);
* `uz.railtech.erp.cabinet.message_posted.v1` — в очереди, в транзакции inbox: сообщение контакта в
  чат кабинета — беседа канала `cabinet` и очередь «Сообщения» (CHAT-1); пост передачи в канале
  команды — после коммита;
* `uz.railtech.eds.letter.registered.v1` — в очереди, в транзакции inbox: ВХ, зарегистрированный из
  очереди «Входящая почта» (`source.crm_inbound_mail_id`), — письмо уходит из очереди с номером ВХ
  (W18A-P2); прочие регистрации CRM пропускает.

Типы без обработчика и версии выше поддерживаемой шина записывает как `skipped` и отвечает 200.
Импорт модуля регистрирует обработчики в реестре `rt_bus` по умолчанию.
"""

from rt_bus import Event, subscribe
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_event import CODE_TYPE, INVITE_TYPE, TEST_TYPE, erp_types
from app.bus.runtime import current_container
from app.services.cabinet_chat import POSTED_TYPE
from app.services.contact_telegram import UNLINK_REQUESTED
from app.services.eds_notices import NOTICE_TYPE, SIGNING_EXPIRING_TYPE
from app.services.inbound_mail import LETTER_REGISTERED
from app.services.mail_requests import MAIL_REQUEST_TYPES
from app.services.partner_clients import REJECTED_TYPE as PARTNER_CLIENT_REJECTED
from app.services.partner_clients import REQUESTED_TYPE as PARTNER_CLIENT_REQUESTED


async def on_erp_event(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.apply(session, event)


@subscribe(CODE_TYPE, inline=True)
async def on_acceptance_code(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.deliver_code(event)


@subscribe(INVITE_TYPE, inline=True)
async def on_invite_requested(event: Event, session: AsyncSession) -> None:
    await current_container().erp_events_service.deliver_invite(event)


@subscribe(TEST_TYPE, inline=True)
async def on_contact_telegram_test(event: Event, session: AsyncSession) -> None:
    await current_container().contact_telegram_test.deliver(event)


for _event_type in erp_types():
    subscribe(_event_type)(on_erp_event)


async def on_mail_requested(event: Event, session: AsyncSession) -> None:
    await current_container().mail_requests.accept(session, event)


for _mail_type in MAIL_REQUEST_TYPES:
    subscribe(_mail_type)(on_mail_requested)


@subscribe(PARTNER_CLIENT_REQUESTED)
async def on_partner_client_requested(event: Event, session: AsyncSession) -> None:
    await current_container().partner_clients.accept(session, event)


@subscribe(PARTNER_CLIENT_REJECTED)
async def on_partner_client_rejected(event: Event, session: AsyncSession) -> None:
    await current_container().partner_clients.release(session, event)


@subscribe(NOTICE_TYPE)
async def on_eds_notice(event: Event, session: AsyncSession) -> None:
    await current_container().eds_notices.accept(session, event)


@subscribe(SIGNING_EXPIRING_TYPE)
async def on_signing_authority_expiring(event: Event, session: AsyncSession) -> None:
    await current_container().eds_notices.accept_signing_expiring(session, event)


@subscribe(LETTER_REGISTERED)
async def on_letter_registered(event: Event, session: AsyncSession) -> None:
    await current_container().inbound_mail.accept_registered(session, event)


@subscribe(UNLINK_REQUESTED)
async def on_contact_telegram_unlink(event: Event, session: AsyncSession) -> None:
    await current_container().contact_telegram.unlink_requested(session, event)


@subscribe(POSTED_TYPE)
async def on_cabinet_message(event: Event, session: AsyncSession) -> None:
    await current_container().cabinet_chat.accept(session, event)
