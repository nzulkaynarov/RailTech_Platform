"""Партнёр ERP становится клиентом CRM (PART-CRM, решение владельца 2026-11-04).

ERP приглашает партнёра в кабинет и публикует `uz.railtech.erp.partner.client_requested.v1`.
CRM — источник правды по клиентам и контактам, поэтому клиента заводит она (проверенная практика:
один мастер клиента, остальные системы — по событию; SAP Business Partner и Odoo `res.partner` —
одна запись с ролями). Но существующий клиент по совпадению ключа не привязывается сам: так
поступают правила дублей Salesforce и HubSpot — совпадение по ключу есть предложение слияния
человеку (решение архитектора по PR #397), иначе опечатка в ИНН отдала бы партнёру чужие заявки,
КП, документы и контакты.

1. **Поиск.** По `erp_company_id` (клиент уже сопоставлен этой компанией — повтор), затем среди
   активных клиентов по ИНН (по цифрам) и по паре «страна + регистрационный номер» (без пробелов
   и дефисов, регистр не важен).
2. **Исходы.**
   * не нашли — создаём клиента (ответственный — пригласивший сотрудник, если он активен в CRM) и
     контакты; ответ `linked`;
   * нашли по `erp_company_id` — `linked` без изменений (контакты запроса добавляются по e-mail);
   * нашли по ключу клиента, уже сопоставленного ДРУГОЙ компании ERP, — `conflict`: ничего не
     меняем, журнал `client.partner_conflict`, уведомление;
   * нашли по ключу клиента без сопоставления — `pending_confirmation`: ничего не меняем, пишем
     заявку `partner_client_requests`, уведомляем ответственного клиента (иначе администраторов).
     Менеджер в карточке клиента подтверждает («Это та же компания» → `linked`, клиент
     сопоставляется, контакты запроса добавляются) или заводит нового клиента («Нет» → `linked`).
3. **Ответ.** `uz.railtech.crm.partner.client_resolved.v1` — идентификаторы клиента и контактов.
   Штатные `crm.client.created/updated` и `crm.contact.created` публикуются как обычно.
4. **Отказ ERP.** `uz.railtech.erp.partner.client_rejected.v1`: ERP не приняла `linked`, потому что
   клиент CRM в ERP уже сопоставлен другой компанией; CRM снимает `erp_company_id`, пишет в журнал
   и уведомляет ответственного.

Идемпотентность: повтор того же события отсекает inbox шины; повторный запрос по той же компании
находит клиента по `erp_company_id`, контакты — по e-mail, ждущую заявку — по компании и
обновляет её; параллельные обработки одной компании (и решение менеджера) сериализует
рекомендательная блокировка Postgres. Иностранной компании страна и регистрационный номер
сохраняются в `clients.country` и `clients.registration_number`; адрес и сайт из запроса — в
заметке нового клиента.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from rt_bus import Event
from rt_contracts.events.erp import PartnerClientRejectedV1, PartnerClientRequestedV1
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import snapshots
from app.domain.erp_handoff import DONE
from app.domain.errors import ConflictError, NotFoundError
from app.models.auth import User
from app.models.clients import Client, ClientContact, PartnerClientRequest
from app.security import audit
from app.security.principal import Principal
from app.services import staff_notifications
from app.services.staff_tickets import admin_user_ids

logger = structlog.get_logger(__name__)

REQUESTED_TYPE: Final = "uz.railtech.erp.partner.client_requested.v1"
REJECTED_TYPE: Final = "uz.railtech.erp.partner.client_rejected.v1"
_LOCK_NAMESPACE: Final = "crm.partner_client"

LINKED: Final = "linked"
PENDING: Final = "pending_confirmation"
CONFLICT: Final = "conflict"

_NOT_DIGIT: Final = re.compile(r"\D")
_REG_SEPARATORS: Final = re.compile(r"[\s\-]")


@dataclass(frozen=True, slots=True)
class _Found:
    client: Client
    matched_by: str


@dataclass(frozen=True, slots=True)
class PartnerRequestView:
    """Ждущая решения заявка для карточки клиента."""

    id: int
    erp_company_id: int
    company_name: str
    matched_by: str
    contacts: list[tuple[str, str]]
    created_at: datetime


def inn_key(value: str | None) -> str | None:
    """Ключ ИНН: только цифры (ведущие нули остаются); пусто — ключа нет."""
    digits = _NOT_DIGIT.sub("", value or "")
    return digits or None


def registration_key(value: str | None) -> str | None:
    """Ключ регистрационного номера: без пробелов и дефисов, регистр не важен."""
    key = _REG_SEPARATORS.sub("", (value or "").lower())
    return key or None


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


async def _lock(session: AsyncSession, erp_company_id: int) -> None:
    """Блокировка до конца транзакции: два запроса по одной компании не создадут двух клиентов."""
    digest = hashlib.sha256(f"{_LOCK_NAMESPACE}:{erp_company_id}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(key)))


async def _find(
    session: AsyncSession,
    erp_company_id: int,
    inn: str | None,
    country: str | None,
    registration_number: str | None,
) -> _Found | None:
    """Клиент по `erp_company_id`, затем среди активных — по ИНН и по паре страна + рег. номер."""
    by_company = await session.scalar(
        select(Client).where(Client.erp_company_id == erp_company_id).order_by(Client.id).limit(1)
    )
    if by_company is not None:
        return _Found(by_company, "erp_company_id")
    inn_digits = inn_key(inn)
    if inn_digits:
        by_inn = await session.scalar(
            select(Client)
            .where(
                Client.is_active.is_(True),
                func.regexp_replace(Client.inn, r"\D", "", "g") == inn_digits,
            )
            .order_by(Client.id)
            .limit(1)
        )
        if by_inn is not None:
            return _Found(by_inn, "inn")
    number = registration_key(registration_number)
    if country and number:
        by_number = await session.scalar(
            select(Client)
            .where(
                Client.is_active.is_(True),
                Client.country == country,
                func.regexp_replace(func.lower(Client.registration_number), r"[\s\-]", "", "g")
                == number,
            )
            .order_by(Client.id)
            .limit(1)
        )
        if by_number is not None:
            return _Found(by_number, "registration_number")
    return None


def _note(company: Any) -> str:
    lines = ["Создан по приглашению партнёра в кабинет клиента (ERP)."]
    if company.address:
        lines.append(f"Адрес: {company.address}")
    if company.website:
        lines.append(f"Сайт: {company.website}")
    return "\n".join(lines)


class PartnerClientService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # --- события шины (транзакция inbox) -------------------------------------------------------

    async def accept(self, session: AsyncSession, event: Event) -> str:
        """Обработать запрос ERP. Исход: `linked`, `pending_confirmation` или `conflict`."""
        data = PartnerClientRequestedV1.model_validate(event.data)
        company = data.company
        erp_company_id = int(data.erp_company_id)
        await _lock(session, erp_company_id)

        country = (_clean(company.country) or "").upper() or None
        found = await _find(
            session,
            erp_company_id,
            _clean(company.inn),
            country,
            _clean(company.registration_number),
        )
        if found is None:
            await self._create(session, data, event.id)
            return LINKED
        if found.matched_by == "erp_company_id":
            await self._link(
                session, found.client, data, found.matched_by, event.id, announce=False
            )
            return LINKED
        if found.client.erp_company_id is not None:  # по ключу найден клиент другой компании ERP
            await self._conflict(session, found.client, erp_company_id, found.matched_by)
            return CONFLICT
        await self._propose(session, found, data)
        return PENDING

    async def release(self, session: AsyncSession, event: Event) -> bool:
        """ERP отклонила `linked` (клиент CRM занят в ERP другой компанией): снять привязку."""
        data = PartnerClientRejectedV1.model_validate(event.data)
        erp_company_id = int(data.erp_company_id)
        await _lock(session, erp_company_id)
        client = await session.get(Client, int(data.crm_client_id), with_for_update=True)
        if client is None or client.erp_company_id != erp_company_id:
            return False
        client.erp_company_id = None
        client.erp_handoff_status = None
        logger.warning(
            "partner_client_released",
            client_id=client.id,
            erp_company_id=erp_company_id,
            other_erp_company_id=data.other_erp_company_id,
        )
        await audit.record(
            session,
            audit.Actor.system(),
            "client.partner_released",
            "client",
            client.id,
            after={
                "erp_company_id": erp_company_id,
                "other_erp_company_id": data.other_erp_company_id,
            },
        )
        await bus_events.client_updated(session, client, audit.Actor.system(), ["erp_company_id"])
        await self._notify(
            session,
            client,
            kind="partner_client_released",
            title=f"Привязка партнёра к «{client.name}» снята: в ERP клиент у другой компании",
            subtitle="Проверьте ИНН или рег. номер у партнёра и у клиента, исправьте ошибочный",
        )
        return True

    # --- карточка клиента: ждущие заявки и решение менеджера -----------------------------------

    @staticmethod
    async def pending_of(session: AsyncSession, client_id: int) -> list[PartnerRequestView]:
        rows = await session.scalars(
            select(PartnerClientRequest)
            .where(
                PartnerClientRequest.client_id == client_id,
                PartnerClientRequest.status == "pending",
            )
            .order_by(PartnerClientRequest.id)
        )
        views = []
        for row in rows:
            data = PartnerClientRequestedV1.model_validate(row.payload)
            views.append(
                PartnerRequestView(
                    id=row.id,
                    erp_company_id=row.erp_company_id,
                    company_name=data.company.name,
                    matched_by=row.matched_by,
                    contacts=[(c.full_name, c.email) for c in data.contacts],
                    created_at=row.created_at,
                )
            )
        return views

    async def confirm(self, who: Principal, client_id: int, request_id: int) -> None:
        """«Это та же компания»: клиент сопоставляется компании ERP, контакты добавляются."""
        async with self._sessions() as session, session.begin():
            row, data = await self._decidable(session, client_id, request_id)
            client = await session.get(Client, client_id, with_for_update=True)
            if client is None:
                raise NotFoundError("client not found")
            if client.erp_company_id not in (None, row.erp_company_id):
                raise ConflictError("client is already linked to another erp company")
            row.status = "confirmed"
            row.decided_by_user_id = who.user_id
            row.decided_at = datetime.now(UTC)
            await self._link(
                session, client, data, row.matched_by, None, announce=True, who=who.actor
            )

    async def decline(self, who: Principal, client_id: int, request_id: int) -> int:
        """«Нет — завести нового клиента»: найденный не тронут. Возвращает id нового клиента."""
        async with self._sessions() as session, session.begin():
            row, data = await self._decidable(session, client_id, request_id)
            row.status = "declined"
            row.decided_by_user_id = who.user_id
            row.decided_at = datetime.now(UTC)
            return await self._create(session, data, None, who=who.actor)

    @staticmethod
    async def _decidable(
        session: AsyncSession, client_id: int, request_id: int
    ) -> tuple[PartnerClientRequest, PartnerClientRequestedV1]:
        row = await session.get(PartnerClientRequest, request_id, with_for_update=True)
        if row is None or row.client_id != client_id or row.status != "pending":
            raise NotFoundError("partner request not found")
        await _lock(session, row.erp_company_id)
        if await session.scalar(
            select(Client.id).where(Client.erp_company_id == row.erp_company_id).limit(1)
        ):
            raise ConflictError("the erp company already has a client")
        return row, PartnerClientRequestedV1.model_validate(row.payload)

    # --- исходы --------------------------------------------------------------------------------

    async def _create(
        self,
        session: AsyncSession,
        data: PartnerClientRequestedV1,
        event_id: str | None,
        *,
        who: audit.Actor | None = None,
    ) -> int:
        company = data.company
        erp_company_id = int(data.erp_company_id)
        inn = _clean(company.inn)
        country = (_clean(company.country) or "").upper() or None
        number = _clean(company.registration_number)
        actor = who or audit.Actor.system()
        client = Client(
            name=company.name.strip(),
            inn=inn,
            country=country if number else None,
            registration_number=number if country else None,
            notes=_note(company),
            owner_user_id=await self._owner(session, data.invited_by_crm_user_id),
            erp_company_id=erp_company_id,
            erp_handoff_status=DONE,
        )
        session.add(client)
        await session.flush()
        await audit.record(
            session,
            actor,
            "client.create",
            "client",
            client.id,
            after={"name": client.name, "source": "erp_partner"},
        )
        await bus_events.client_created(session, client, actor)
        await self._finish(session, client, data, "created", event_id, announce=True, who=actor)
        return client.id

    async def _link(
        self,
        session: AsyncSession,
        client: Client,
        data: PartnerClientRequestedV1,
        matched_by: str,
        event_id: str | None,
        *,
        announce: bool,
        who: audit.Actor | None = None,
    ) -> None:
        """Клиент сопоставлен компании ERP: `erp_company_id`, реквизиты нерезидента (если пусто)."""
        actor = who or audit.Actor.system()
        erp_company_id = int(data.erp_company_id)
        changed: list[str] = []
        if client.erp_company_id is None:
            client.erp_company_id = erp_company_id
            changed.append("erp_company_id")
            if client.erp_handoff_status is None:
                client.erp_handoff_status = DONE
        country = (_clean(data.company.country) or "").upper() or None
        number = _clean(data.company.registration_number)
        if country and number and not client.registration_number:
            client.country, client.registration_number = country, number
        if changed:
            await bus_events.client_updated(session, client, actor, changed)
        await self._finish(
            session, client, data, matched_by, event_id, announce=announce, who=actor
        )

    async def _finish(
        self,
        session: AsyncSession,
        client: Client,
        data: PartnerClientRequestedV1,
        matched_by: str,
        event_id: str | None,
        *,
        announce: bool,
        who: audit.Actor,
    ) -> None:
        contacts = await self._contacts(session, client, data)
        if announce:  # повтор по уже сопоставленному клиенту — без журнала и уведомления
            await audit.record(
                session,
                who,
                "client.partner_linked",
                "client",
                client.id,
                after={
                    "erp_company_id": int(data.erp_company_id),
                    "matched_by": matched_by,
                    "event_id": event_id,
                },
            )
            await self._notify(
                session,
                client,
                kind="partner_client_new" if matched_by == "created" else "partner_client_linked",
                title=(
                    f"Новый клиент из кабинета партнёра: «{client.name}»"
                    if matched_by == "created"
                    else f"Клиент «{client.name}» стал партнёром в кабинете"
                ),
                subtitle="Заявки партнёра придут в карточку клиента как обычные заявки",
            )
        await bus_events.partner_client_resolved(
            session,
            erp_company_id=int(data.erp_company_id),
            status=LINKED,
            crm_client_id=client.id,
            matched_by=matched_by,
            contacts=contacts,
        )

    async def _propose(
        self, session: AsyncSession, found: _Found, data: PartnerClientRequestedV1
    ) -> None:
        """Нашли клиента по ключу, он ничей: ничего не меняем, ждём решения менеджера."""
        erp_company_id = int(data.erp_company_id)
        payload = data.model_dump(mode="json")
        row = await session.scalar(
            select(PartnerClientRequest)
            .where(
                PartnerClientRequest.erp_company_id == erp_company_id,
                PartnerClientRequest.status == "pending",
            )
            .with_for_update()
        )
        is_new = row is None
        if row is None:
            row = PartnerClientRequest(erp_company_id=erp_company_id)
            session.add(row)
        row.client_id, row.matched_by, row.payload = found.client.id, found.matched_by, payload
        await session.flush()
        if is_new:  # повторное приглашение обновляет заявку, но не шлёт то же уведомление снова
            await audit.record(
                session,
                audit.Actor.system(),
                "client.partner_pending",
                "client",
                found.client.id,
                after={"erp_company_id": erp_company_id, "matched_by": found.matched_by},
            )
            await self._notify(
                session,
                found.client,
                kind="partner_client_confirm",
                title=f"Партнёр из ERP похож на клиента «{found.client.name}»: это та же компания?",
                subtitle="В карточке клиента: «Это та же компания» или «Нет — завести нового»",
            )
        await bus_events.partner_client_resolved(
            session,
            erp_company_id=erp_company_id,
            status=PENDING,
            crm_client_id=found.client.id,
            matched_by=found.matched_by,
        )

    async def _conflict(
        self, session: AsyncSession, client: Client, erp_company_id: int, matched_by: str
    ) -> None:
        """Клиент сопоставлен другой компании ERP: не меняем, журнал + уведомление + ответ ERP."""
        logger.warning(
            "partner_client_conflict",
            client_id=client.id,
            erp_company_id=erp_company_id,
            existing_erp_company_id=client.erp_company_id,
        )
        await audit.record(
            session,
            audit.Actor.system(),
            "client.partner_conflict",
            "client",
            client.id,
            after={
                "erp_company_id": erp_company_id,
                "existing_erp_company_id": client.erp_company_id,
                "matched_by": matched_by,
            },
        )
        await self._notify(
            session,
            client,
            kind="partner_client_conflict",
            title=f"Партнёр из ERP совпал с «{client.name}», а тот привязан к другой компании",
            subtitle="Ничего не изменено: проверьте ИНН или рег. номер у партнёра и у клиента",
        )
        await bus_events.partner_client_resolved(
            session,
            erp_company_id=erp_company_id,
            status=CONFLICT,
            crm_client_id=client.id,
            conflict_erp_company_id=client.erp_company_id,
        )

    # --- вспомогательное -----------------------------------------------------------------------

    @staticmethod
    async def _owner(session: AsyncSession, crm_user_id: int | None) -> int | None:
        if crm_user_id is None:
            return None
        user = await session.get(User, crm_user_id)
        return user.id if user is not None and user.is_active else None

    @staticmethod
    async def _contacts(
        session: AsyncSession, client: Client, data: PartnerClientRequestedV1
    ) -> list[dict[str, int]]:
        """Контакты запроса: найти по e-mail у клиента, иначе создать.

        Возвращает пары `erp_contact_id` ↔ `crm_contact_id`.
        """
        has_primary = bool(
            await session.scalar(
                select(ClientContact.id)
                .where(ClientContact.client_id == client.id, ClientContact.is_primary.is_(True))
                .limit(1)
            )
        )
        pairs: list[dict[str, int]] = []
        seen: dict[str, int] = {}
        for item in data.contacts:
            email = item.email.strip().lower()
            row_id = seen.get(email)
            if row_id is None:
                row = await session.scalar(
                    select(ClientContact)
                    .where(
                        ClientContact.client_id == client.id,
                        func.lower(ClientContact.email) == email,
                    )
                    .order_by(ClientContact.id)
                    .limit(1)
                )
                if row is None:
                    row = ClientContact(
                        client_id=client.id,
                        full_name=item.full_name.strip(),
                        email=email,
                        phone_e164=snapshots.clean_phone(item.phone),
                        is_primary=not has_primary,
                        preferred_channel="email",
                    )
                    has_primary = True
                    session.add(row)
                    await session.flush()
                    await bus_events.contact_created(session, row, audit.Actor.system())
                row_id = row.id
                seen[email] = row_id
            pairs.append({"erp_contact_id": int(item.erp_contact_id), "crm_contact_id": row_id})
        return pairs

    @staticmethod
    async def _notify(
        session: AsyncSession, client: Client, *, kind: str, title: str, subtitle: str
    ) -> None:
        """Ответственному за клиента, иначе администраторам (вкладка «Клиенты» колокольчика)."""
        recipients = (
            [client.owner_user_id] if client.owner_user_id else await admin_user_ids(session)
        )
        staff_notifications.add_in(
            session,
            recipients,
            kind=kind,
            tab="clients",
            title=title,
            subtitle=subtitle,
        )
