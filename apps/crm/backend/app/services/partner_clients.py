"""Партнёр ERP становится клиентом CRM (PART-CRM, решение владельца 2026-11-04).

ERP приглашает партнёра в кабинет и публикует `uz.railtech.erp.partner.client_requested.v1`.
CRM — источник правды по клиентам и контактам, поэтому клиента заводит она (проверенная практика:
один мастер клиента, остальные системы — по событию; SAP Business Partner и Odoo `res.partner` —
одна запись с ролями):

1. **Клиент.** Ищем по `erp_company_id` (уже сопоставлен — повтор), затем по ИНН, затем по паре
   «страна + регистрационный номер» (иностранная компания); не нашли — создаём. Нашли клиента,
   уже сопоставленного ДРУГОЙ компании ERP, — **конфликт**: ничего не перезаписываем, пишем в
   журнал аудита (`client.partner_conflict`), уведомляем ответственного (иначе администраторов)
   и отвечаем ERP `status = conflict`.
2. **Ответственный** нового клиента — сотрудник, пригласивший партнёра
   (`invited_by_crm_user_id`), если он активен в CRM; иначе клиент остаётся без ответственного,
   а уведомление уходит администраторам.
3. **Контакты.** Контакт клиента с тем же e-mail (без учёта регистра) берётся, иначе создаётся
   (канал — e-mail). Основным становится первый контакт, только если основного у клиента нет.
4. **Ответ.** `uz.railtech.crm.partner.client_resolved.v1` — идентификаторы клиента и контактов;
   ERP по нему ставит сопоставление и тип CLIENT. Штатные `crm.client.created/updated` и
   `crm.contact.created` публикуются как обычно.

Идемпотентность: повтор того же события отсекает inbox шины; повторный запрос по той же компании
находит клиента по `erp_company_id`, а контакты — по e-mail, ничего не задваивается; параллельные
обработки одной компании сериализует рекомендательная блокировка Postgres. Иностранной компании
страна и регистрационный номер сохраняются в `clients.country` и `clients.registration_number`;
адрес и сайт из запроса — в заметке нового клиента (отдельных полей в CRM нет).
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Final

import structlog
from rt_bus import Event
from rt_contracts.events.erp import PartnerClientRequestedV1
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.bus import snapshots
from app.domain.erp_handoff import DONE
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.security import audit
from app.services import staff_notifications
from app.services.staff_tickets import admin_user_ids

logger = structlog.get_logger(__name__)

REQUESTED_TYPE: Final = "uz.railtech.erp.partner.client_requested.v1"
_LOCK_NAMESPACE: Final = "crm.partner_client"


@dataclass(frozen=True, slots=True)
class _Found:
    client: Client
    matched_by: str


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
    """Клиент по `erp_company_id`, по ИНН, по паре «страна + регистрационный номер» (меньший id)."""
    by_company = await session.scalar(
        select(Client).where(Client.erp_company_id == erp_company_id).order_by(Client.id).limit(1)
    )
    if by_company is not None:
        return _Found(by_company, "erp_company_id")
    if inn:
        by_inn = await session.scalar(
            select(Client).where(Client.inn == inn).order_by(Client.id).limit(1)
        )
        if by_inn is not None:
            return _Found(by_inn, "inn")
    if country and registration_number:
        by_number = await session.scalar(
            select(Client)
            .where(
                Client.country == country,
                func.lower(Client.registration_number) == registration_number.lower(),
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
    async def accept(self, session: AsyncSession, event: Event) -> str:
        """Обработать запрос ERP в транзакции inbox. Исход: `linked` или `conflict`."""
        data = PartnerClientRequestedV1.model_validate(event.data)
        company = data.company
        erp_company_id = int(data.erp_company_id)
        await _lock(session, erp_company_id)

        inn = _clean(company.inn)
        country = _clean(company.country)
        country = country.upper() if country else None
        registration_number = _clean(company.registration_number)
        found = await _find(session, erp_company_id, inn, country, registration_number)

        if found is not None and found.client.erp_company_id not in (None, erp_company_id):
            await self._conflict(session, found.client, erp_company_id, found.matched_by)
            return "conflict"

        owner = await self._owner(session, data.invited_by_crm_user_id)
        actor = audit.Actor.system()
        created = found is None
        if found is None:
            client = Client(
                name=company.name.strip(),
                inn=inn,
                country=country if registration_number else None,
                registration_number=registration_number if country else None,
                notes=_note(company),
                owner_user_id=owner,
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
            matched_by = "created"
        else:
            client, matched_by = found.client, found.matched_by
            changed = self._complete(client, erp_company_id, country, registration_number)
            if changed:
                await bus_events.client_updated(session, client, actor, changed)

        contacts = await self._contacts(session, client, data)
        if (
            created or matched_by != "erp_company_id"
        ):  # повтор по уже сопоставленному клиенту — без журнала и уведомления
            await audit.record(
                session,
                actor,
                "client.partner_linked",
                "client",
                client.id,
                after={
                    "erp_company_id": erp_company_id,
                    "matched_by": matched_by,
                    "event_id": event.id,
                },
            )
            await self._notify_linked(session, client, created)
        await bus_events.partner_client_resolved(
            session,
            erp_company_id=erp_company_id,
            status="linked",
            crm_client_id=client.id,
            matched_by=matched_by,
            contacts=contacts,
        )
        return "linked"

    @staticmethod
    def _complete(
        client: Client, erp_company_id: int, country: str | None, registration_number: str | None
    ) -> list[str]:
        """Найденному клиенту — сопоставление с ERP и (если пусто) реквизиты нерезидента.

        Имя и ИНН не трогаем.
        """
        changed: list[str] = []
        if client.erp_company_id is None:
            client.erp_company_id = erp_company_id
            changed.append("erp_company_id")
            if client.erp_handoff_status is None:
                client.erp_handoff_status = DONE
        if country and registration_number and not client.registration_number:
            client.country, client.registration_number = country, registration_number
        return changed

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

    async def _conflict(
        self, session: AsyncSession, client: Client, erp_company_id: int, matched_by: str
    ) -> None:
        """Клиент сопоставлен другой компании ERP: не меняем, журнал, уведомление, ответ ERP."""
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
            subtitle="Ничего не изменено: объедините карточки и пригласите партнёра ещё раз",
        )
        await bus_events.partner_client_resolved(
            session,
            erp_company_id=erp_company_id,
            status="conflict",
            crm_client_id=client.id,
            conflict_erp_company_id=client.erp_company_id,
        )

    async def _notify_linked(self, session: AsyncSession, client: Client, created: bool) -> None:
        await self._notify(
            session,
            client,
            kind="partner_client_new" if created else "partner_client_linked",
            title=(
                f"Новый клиент из кабинета партнёра: «{client.name}»"
                if created
                else f"Клиент «{client.name}» стал партнёром в кабинете"
            ),
            subtitle="Заявки партнёра придут в карточку клиента как обычные заявки",
        )

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
