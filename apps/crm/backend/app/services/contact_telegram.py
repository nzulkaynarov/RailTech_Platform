"""Telegram контакта без подтверждения менеджера (NOTIFY-1, ADR-0023 п. 3): привязка по ссылке
из кабинета и отключение по запросу ERP.

Привязка. Контакт в кабинете (Профиль → «Уведомления») получает от ERP одноразовую ссылку
`t.me/<бот>?start=tg_…`; бот после приветствия (`ConversationService.start` уже завёл
Telegram-идентичность) передаёт параметр сюда. В одной транзакции: подпись и срок
(`domain/contact_link.py`), погашение nonce (`telegram_link_nonces`, `INSERT … ON CONFLICT DO
NOTHING`: повтор и параллельный повтор — один выигравший), привязка Telegram к контакту
(`ClientContact.telegram_identity_id`) и к клиенту с отметкой подтверждения (`verified_at`, без
`verified_by_user_id` — подтвердил сам контакт ссылкой из своей сессии), лид этого Telegram —
клиенту (как при подтверждении менеджером), аудит и `crm.contact.updated` с `telegram_user_id` в
outbox. ERP по нему заполняет проекцию — Mini App входит.

Безопасность. Повтор, чужой, подделанный и просроченный токен и токен несуществующего контакта
получают один нейтральный отказ (не выдаём, существует ли контакт). Telegram, уже связанный с
другим клиентом или с другим контактом, молча не перепривязывается (как
`ClientService.link_identity` — `TELEGRAM_LINKED_ELSEWHERE`): отдельный ответ «уже связан с другим
контактом» — он говорит человеку только о его собственном Telegram, о контакте из ссылки — ничего;
транзакция откатывается, ссылка остаётся неиспользованной.

Отключение. ERP публикует `uz.railtech.erp.contact.telegram_unlink_requested.v1` (поле принадлежит
CRM, ADR-0015); здесь, в транзакции inbox, контакт теряет Telegram, а Telegram — клиента и
подтверждение (`_release_telegram`; лид, его клиент и стадия не меняются — отключение уведомлений
не потеря клиента), и уходит `crm.contact.updated` без `telegram_user_id`. Повтор и уже
отвязанный контакт — без действий. Повторная привязка другим аккаунтом освобождает прежний так же.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import structlog
from rt_bus import Event
from rt_contracts.events.erp import ContactTelegramUnlinkRequestedV1
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain import client_texts, contact_link
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity, TelegramLinkNonce
from app.security import audit
from app.services.leads import ChatsChanged, notify_chats

logger = structlog.get_logger(__name__)

__all__ = ["UNLINK_REQUESTED", "ContactTelegramService", "PairSecrets"]

UNLINK_REQUESTED = "uz.railtech.erp.contact.telegram_unlink_requested.v1"
#: Действующие секреты пары шины `erp → crm` (первый — текущий, затем прежний); перед чтением кэш
#: секретов обновляется.
PairSecrets = Callable[[], Awaitable[Sequence[str]]]


class _RefusedError(Exception):
    """Нейтральный отказ: причина — только в журнал."""


class _TakenError(Exception):
    """Telegram уже связан с другим клиентом или контактом."""


class ContactTelegramService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        pair_secrets: PairSecrets,
        on_chats_changed: ChatsChanged | None = None,
    ) -> None:
        self._sessions = sessions
        self._pair_secrets = pair_secrets
        self._on_chats_changed = on_chats_changed

    async def bind(self, tg_user_id: int, raw: str, now: datetime | None = None) -> list[str]:
        """Тексты бота после `/start tg_…`: приветствие на языке контакта или отказ на языке
        чата."""
        moment = now or datetime.now(UTC)
        link = contact_link.verify(raw, await self._pair_secrets(), moment)
        if link is None:
            logger.info("contact_link_refused", reason="invalid_or_expired")
            return [client_texts.contact_link_refused(await self._chat_language(tg_user_id))]
        try:
            async with self._sessions() as session, session.begin():
                company = await self._bind(session, tg_user_id, link, moment)
        except _RefusedError as refused:
            logger.info("contact_link_refused", reason=str(refused))
            return [client_texts.contact_link_refused(await self._chat_language(tg_user_id))]
        except _TakenError:
            logger.info("contact_link_refused", reason="telegram_linked_elsewhere")
            return [client_texts.contact_link_taken(await self._chat_language(tg_user_id))]
        await notify_chats(self._on_chats_changed, [tg_user_id])
        return [client_texts.contact_link_bound(link.language, company)]

    async def _bind(
        self,
        session: AsyncSession,
        tg_user_id: int,
        link: contact_link.ContactLink,
        moment: datetime,
    ) -> str:
        """Погасить nonce и привязать; отказ — исключением (транзакция откатывается). Возвращает
        название компании."""
        used = await session.scalar(
            insert(TelegramLinkNonce)
            .values(
                nonce=link.nonce,
                crm_contact_id=link.crm_contact_id,
                tg_user_id=tg_user_id,
                expires_at=link.expires_at,
            )
            .on_conflict_do_nothing(index_elements=["nonce"])
            .returning(TelegramLinkNonce.nonce)
        )
        if used is None:
            raise _RefusedError("replayed")
        contact = await session.get(ClientContact, link.crm_contact_id, with_for_update=True)
        if contact is None:
            raise _RefusedError("no_contact")
        identity = await session.scalar(
            select(TelegramIdentity)
            .where(TelegramIdentity.tg_user_id == tg_user_id)
            .with_for_update()
        )
        if identity is None:
            raise _RefusedError("no_identity")
        if identity.client_id not in (None, contact.client_id) or await _other_contact(
            session, identity.id, contact.id
        ):
            raise _TakenError
        actor = audit.Actor.system()
        before = {
            "contact_id": contact.id,
            "telegram_identity_id": contact.telegram_identity_id,
            "verified_by_user_id": identity.verified_by_user_id,
        }
        after: dict[str, object] = {}
        previous_id = contact.telegram_identity_id
        if previous_id is not None and previous_id != identity.id:
            # Повторная привязка другим аккаунтом: прежний Telegram контакта больше не аккаунт
            # клиента — иначе он получал бы уведомления, а из кабинета его не отключить.
            after |= await _release_previous(session, previous_id, contact, moment)
        if identity.client_id != contact.client_id or identity.verified_at is None:
            identity.verified_at, identity.verified_by_user_id = moment, None
        # Уже подтверждённый менеджером Telegram этого клиента сохраняет `verified_by_user_id`.
        identity.client_id = contact.client_id
        identity.notifications_off_at = None  # подключил снова — рассылки клиента снова идут сюда
        contact.telegram_identity_id = identity.id
        if identity.lead_id is not None:
            lead = await session.get(Lead, identity.lead_id, with_for_update=True)
            if lead is not None and lead.client_id is None:
                lead.client_id = contact.client_id
                await bus_events.lead_updated(session, lead, actor, ["crm_client_id"])
        await audit.record(
            session,
            actor,
            "client.contact_telegram_self_link",
            "client",
            contact.client_id,
            before=before,
            after={
                "contact_id": contact.id,
                "telegram_identity_id": identity.id,
                "tg_user_id": tg_user_id,
                "verified_by_user_id": identity.verified_by_user_id,
                **after,
            },
        )
        await bus_events.contact_updated(session, contact, actor)
        return await session.scalar(select(Client.name).where(Client.id == contact.client_id)) or ""

    async def _chat_language(self, tg_user_id: int) -> str | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(Lead.language)
                .join(TelegramIdentity, TelegramIdentity.lead_id == Lead.id)
                .where(TelegramIdentity.tg_user_id == tg_user_id)
            )

    async def unlink_requested(self, session: AsyncSession, event: Event) -> None:
        """`erp.contact.telegram_unlink_requested` в транзакции inbox; повтор и отвязанный контакт
        — без действий."""
        data = ContactTelegramUnlinkRequestedV1.model_validate(event.data)
        crm_contact_id = data.payload.crm_contact_id
        contact = await session.get(ClientContact, crm_contact_id, with_for_update=True)
        if contact is None or contact.client_id != data.crm_client_id:
            logger.warning(
                "contact_telegram_unlink_skipped",
                crm_contact_id=crm_contact_id,
                reason="not_this_client",
            )
            return
        identity_id = contact.telegram_identity_id
        if identity_id is None:
            return
        contact.telegram_identity_id = None
        actor = audit.Actor.system()
        after: dict[str, object] = {"contact_id": contact.id, "telegram_identity_id": None}
        identity = await session.get(TelegramIdentity, identity_id, with_for_update=True)
        if (
            identity is not None
            and identity.client_id == contact.client_id
            and not await _other_contact(session, identity.id, contact.id)
        ):
            after |= _release_telegram(identity, datetime.now(UTC))
        await audit.record(
            session,
            actor,
            "client.contact_telegram_self_unlink",
            "client",
            contact.client_id,
            before={"contact_id": contact.id, "telegram_identity_id": identity_id},
            after=after,
        )
        await bus_events.contact_updated(session, contact, actor)


async def _other_contact(session: AsyncSession, identity_id: int, contact_id: int) -> bool:
    found = await session.scalar(
        select(ClientContact.id)
        .where(ClientContact.telegram_identity_id == identity_id, ClientContact.id != contact_id)
        .limit(1)
    )
    return found is not None


def _release_telegram(identity: TelegramIdentity, moment: datetime) -> dict[str, object]:
    """Отключение Telegram самим контактом: аккаунт больше не Telegram клиента (снимаются клиент и
    подтверждение — бот не шлёт ему уведомления клиента, Mini App не входит). Лид этого Telegram,
    его `client_id` и стадия **не меняются**: отключение уведомлений — не потеря клиента, и
    повторное подключение возвращает всё как было (отвязка менеджером —
    `ClientService.unlink_identity` — другое действие и откатывает стадию)."""
    released: dict[str, object] = {
        "tg_user_id": identity.tg_user_id,
        "verified_by_user_id_before": identity.verified_by_user_id,
    }
    identity.client_id, identity.verified_at, identity.verified_by_user_id = None, None, None
    # Лид остаётся клиентом, поэтому рассылки «через лида клиента» (отслеживание запроса D1-9,
    # приглашение) взяли бы этот аккаунт — отметка их выключает до повторного подключения.
    identity.notifications_off_at = moment
    return released


async def _release_previous(
    session: AsyncSession, identity_id: int, contact: ClientContact, moment: datetime
) -> dict[str, object]:
    previous = await session.get(TelegramIdentity, identity_id, with_for_update=True)
    if (
        previous is None
        or previous.client_id != contact.client_id
        or await _other_contact(session, previous.id, contact.id)
    ):
        return {}
    return {"released": _release_telegram(previous, moment)}


async def republish_contacts_of(
    session: AsyncSession, identity_ids: Sequence[int], actor: audit.Actor
) -> None:
    """Telegram контакта изменился у CRM (обезличен по `/delete`, сменил имя или ник) — контакты,
    к которым он привязан, снова уходят `crm.contact.updated`: ERP заменит или сотрёт имя аккаунта в
    проекции (NOTIFY-1). `updated_at` контакта сдвигается, иначе ERP примет снимок за повтор."""
    if not identity_ids:
        return
    ids = (
        await session.scalars(
            update(ClientContact)
            .where(ClientContact.telegram_identity_id.in_(list(identity_ids)))
            .values(updated_at=func.now())
            .returning(ClientContact.id)
        )
    ).all()
    for contact_id in ids:
        contact = await session.get(ClientContact, contact_id, populate_existing=True)
        if contact is not None:
            await bus_events.contact_updated(session, contact, actor)


async def sync_telegram_names(
    session: AsyncSession, identity: TelegramIdentity, username: str | None, first_name: str
) -> None:
    """Ник или имя Telegram сменились (NOTIFY-1): кабинет показывает контакту `@аккаунт`, поэтому
    имена обновляются и контакт, к которому привязан этот Telegram, публикуется заново. Только при
    реальной смене; вызывающий передаёт полный профиль отправителя (`first_name` есть всегда)."""
    if (identity.tg_username, identity.tg_first_name) == (username, first_name):
        return
    identity.tg_username, identity.tg_first_name = username, first_name
    await republish_contacts_of(session, [identity.id], audit.Actor(None, "bot"))


async def unlink_erased(
    session: AsyncSession, identity_ids: Sequence[int], moment: datetime, actor: audit.Actor
) -> None:
    """`/delete` (решение архитектора 2026-11-04): Telegram обезличенного лида отвязывается от
    контактов — снимаются привязка, клиент и подтверждение, ставится `notifications_off_at`, а
    контакты уходят `crm.contact.updated` без `telegram_user_id` и имён (Mini App закрыт). Новое
    сообщение того же человека — новое анонимное обращение; имена в ERP снова попадут, только когда
    контакт сам привяжет Telegram по ссылке из кабинета (привязка и есть согласие)."""
    if not identity_ids:
        return
    contacts = (
        await session.scalars(
            select(ClientContact)
            .where(ClientContact.telegram_identity_id.in_(list(identity_ids)))
            .with_for_update()
        )
    ).all()
    identities = (
        await session.scalars(
            select(TelegramIdentity)
            .where(TelegramIdentity.id.in_(list(identity_ids)))
            .with_for_update()
        )
    ).all()
    for identity in identities:
        _release_telegram(identity, moment)
    for contact in contacts:
        contact.telegram_identity_id = None
        await audit.record(
            session,
            actor,
            "client.contact_telegram_self_unlink",
            "client",
            contact.client_id,
            after={"contact_id": contact.id, "reason": "erased"},
        )
        await bus_events.contact_updated(session, contact, actor)
