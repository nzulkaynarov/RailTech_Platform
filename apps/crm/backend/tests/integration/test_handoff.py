"""Интеграционные тесты передачи лида/клиента в бэк-офис ERP (M3-CRM-03, ADR-0022).

Проверка сквозного сценария:
- Переход из in_progress в customer при backoffice_mode == 'erp'
- Создание / связывание компании (erp_company_id) и заявки (erp_deal_id, external_stage='request')
- Создание ClientContact и привязка TelegramIdentity
- Откат транзакции при сбое ERP
- Обратная совместимость в режиме 'local'
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.domain.stages import Stage
from app.integrations.erp import HandoffPayload, HandoffResult
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.security.principal import Principal
from app.services.clients import ClientService
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LeadService
from app.services.settings import SettingsService
from tests.integration.crm_helpers import FakeSender, make_user

pytestmark = pytest.mark.integration

CONSENT_AT = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
CONSENT_VERSION = "2026-10-08"


class FakeErpClient:
    def __init__(
        self,
        *,
        company_id: int = 101,
        request_id: int | None = 202,
        fail: bool = False,
    ) -> None:
        self.company_id = company_id
        self.request_id = request_id
        self.fail = fail
        self.calls: list[HandoffPayload] = []

    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult:
        self.calls.append(payload)
        if self.fail:
            raise UpstreamUnavailableError("erp down", reason=Reason.ERP_UNAVAILABLE)
        return HandoffResult(
            erp_company_id=self.company_id,
            erp_request_id=self.request_id,
            invite_sent_via=["telegram"],
            cabinet_url="https://cabinet.internal/magic/1",
        )


async def _create_lead(
    session: AsyncSession,
    *,
    stage: str = "in_progress",
    tg_user_id: int = 77001,
    assigned_user_id: int | None = None,
    consent_at: datetime | None = CONSENT_AT,
    consent_version: str | None = CONSENT_VERSION,
) -> int:
    lead = Lead(
        display_name="ООО Логистик Плюс",
        stage=stage,
        owner_mode="human",
        assigned_user_id=assigned_user_id,
        need_summary="Требуются 50 вагонов",
        product_interest=["wagons"],
        phone_e164="+998901112233",
        language="ru",
        consent_given_at=consent_at,
        consent_version=consent_version,
    )
    session.add(lead)
    await session.flush()
    identity = TelegramIdentity(
        tg_user_id=tg_user_id,
        tg_first_name="Алишер",
        tg_username="alisher_log",
        phone_e164="+998901112233",
        lead_id=lead.id,
    )
    session.add(identity)
    await session.flush()
    return lead.id


async def test_make_customer_erp_mode_success(sessions: async_sessionmaker[AsyncSession]) -> None:
    account, _ = await make_user(sessions, "manager1@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(session, stage="in_progress", assigned_user_id=account.id)

    fake_erp = FakeErpClient(company_id=55, request_id=77)

    async def _erp_mode() -> BackofficeMode:
        return BackofficeMode.ERP

    service = ClientService(
        sessions,
        backoffice_mode=_erp_mode,
        erp_client=fake_erp,
    )

    client_id = await service.make_customer(
        who, lead_id, client_id=None, new_name="ООО Логистик Плюс"
    )

    assert client_id > 0
    assert len(fake_erp.calls) == 1
    call = fake_erp.calls[0]
    assert call.crm_client_id == client_id
    assert call.crm_lead_id == lead_id
    assert call.company.name == "ООО Логистик Плюс"
    assert len(call.contacts) >= 1
    assert call.contacts[0].telegram_user_id == 77001

    async with sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id == 55

        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.stage == Stage.CUSTOMER.value
        assert lead.owner_mode == "bot"
        assert lead.client_id == client_id

        # Проверяем, что создана сделка с erp_deal_id
        deal = (
            await session.scalars(
                select(Deal).where(Deal.lead_id == lead_id).order_by(Deal.id.desc())
            )
        ).first()
        assert deal is not None
        assert deal.erp_deal_id == 77
        assert deal.external_stage == "request"
        assert deal.client_id == client_id

        # Проверяем контакт
        contact = (
            await session.scalars(select(ClientContact).where(ClientContact.client_id == client_id))
        ).first()
        assert contact is not None
        assert contact.is_primary is True
        assert contact.full_name == "ООО Логистик Плюс"


async def test_make_customer_erp_mode_failure_rolls_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    account, _ = await make_user(sessions, "manager2@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(session, stage="in_progress", assigned_user_id=account.id)

    fake_erp = FakeErpClient(fail=True)

    async def _erp_mode() -> BackofficeMode:
        return BackofficeMode.ERP

    service = ClientService(
        sessions,
        backoffice_mode=_erp_mode,
        erp_client=fake_erp,
    )

    with pytest.raises(UpstreamUnavailableError):
        await service.make_customer(who, lead_id, client_id=None, new_name="Сбойная Компания")

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        # Стадия не должна измениться
        assert lead.stage == "in_progress"
        assert lead.client_id is None

        # Клиент не должен сохраниться в базе
        clients = (
            await session.scalars(select(Client).where(Client.name == "Сбойная Компания"))
        ).all()
        assert len(clients) == 0


async def test_make_customer_local_mode_preserves_legacy_behavior(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    account, _ = await make_user(sessions, "manager3@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        # В local режиме передача разрешена только из won (или customer)
        lead_id = await _create_lead(session, stage="won", assigned_user_id=account.id)

    fake_erp = FakeErpClient(company_id=99)

    service = ClientService(sessions, erp_client=fake_erp)  # default backoffice_mode is local

    client_id = await service.make_customer(who, lead_id, client_id=None, new_name="Локал Клиент")

    # В режиме local ERP не вызывается
    assert len(fake_erp.calls) == 0

    async with sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id is None

        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.stage == Stage.CUSTOMER.value


async def _erp_mode() -> BackofficeMode:
    return BackofficeMode.ERP


async def test_consent_goes_to_erp_exactly_as_the_lead_gave_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """I-13: время и версия — из лида, не «сейчас» и не «1.0»."""
    account, _ = await make_user(sessions, "manager4@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(session, assigned_user_id=account.id)
    fake_erp = FakeErpClient()

    service = ClientService(sessions, backoffice_mode=_erp_mode, erp_client=fake_erp)
    await service.make_customer(who, lead_id, client_id=None, new_name="Согласная Компания")

    consent = fake_erp.calls[0].consent
    assert datetime.fromisoformat(consent.given_at) == CONSENT_AT
    assert consent.version == CONSENT_VERSION


@pytest.mark.parametrize(
    ("consent_at", "consent_version"),
    [(None, None), (None, CONSENT_VERSION), (CONSENT_AT, None), (CONSENT_AT, "")],
)
async def test_lead_without_consent_is_not_handed_off(
    sessions: async_sessionmaker[AsyncSession],
    consent_at: datetime | None,
    consent_version: str | None,
) -> None:
    """I-13: согласия нет — 422 менеджеру, ERP не вызывается, в CRM ничего не меняется."""
    account, _ = await make_user(sessions, "manager5@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(
            session,
            assigned_user_id=account.id,
            consent_at=consent_at,
            consent_version=consent_version,
        )
    fake_erp = FakeErpClient()

    service = ClientService(sessions, backoffice_mode=_erp_mode, erp_client=fake_erp)
    with pytest.raises(ValidationFailedError) as exc_info:
        await service.make_customer(who, lead_id, client_id=None, new_name="Без Согласия")

    assert exc_info.value.details["reason"] == Reason.HANDOFF_NO_CONSENT.value
    assert fake_erp.calls == []
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.client_id) == ("in_progress", None)
        assert (
            await session.scalars(select(Client).where(Client.name == "Без Согласия"))
        ).first() is None


async def test_local_mode_does_not_need_consent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Без коннектора ERP согласие никуда не передаётся — поведение режима local как было."""
    account, _ = await make_user(sessions, "manager6@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(
            session,
            stage="won",
            assigned_user_id=account.id,
            consent_at=None,
            consent_version=None,
        )

    client_id = await ClientService(sessions).make_customer(
        who, lead_id, None, "Локал Без Согласия"
    )

    assert client_id > 0


async def test_client_made_in_local_mode_is_handed_to_erp_after_switch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """I-14: стал клиентом в режиме local, потом подключили ERP — повторная передача доходит."""
    account, _ = await make_user(sessions, "manager7@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(session, stage="won", assigned_user_id=account.id)
    fake_erp = FakeErpClient(company_id=61, request_id=62)

    local_client_id = await ClientService(sessions, erp_client=fake_erp).make_customer(
        who, lead_id, None, "Клиент До ERP"
    )
    assert fake_erp.calls == []  # режим local: ERP не вызывается
    async with sessions() as session:
        client = await session.get(Client, local_client_id)
        assert client is not None
        assert client.erp_company_id is None

    after_switch = ClientService(sessions, backoffice_mode=_erp_mode, erp_client=fake_erp)
    again = await after_switch.make_customer(who, lead_id, local_client_id, None)

    assert again == local_client_id
    assert len(fake_erp.calls) == 1
    assert fake_erp.calls[0].crm_client_id == local_client_id
    async with sessions() as session:
        client = await session.get(Client, local_client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        assert client.erp_company_id == 61
        assert lead is not None
        assert lead.stage == "customer"

    # Клиент уже в ERP — следующая передача ничего не делает.
    await after_switch.make_customer(who, lead_id, local_client_id, None)
    assert len(fake_erp.calls) == 1


async def test_resync_without_consent_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    account, _ = await make_user(sessions, "manager8@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(
            session,
            stage="won",
            assigned_user_id=account.id,
            consent_at=None,
            consent_version=None,
        )
    fake_erp = FakeErpClient()
    client_id = await ClientService(sessions).make_customer(who, lead_id, None, "Старый Клиент")

    after_switch = ClientService(sessions, backoffice_mode=_erp_mode, erp_client=fake_erp)
    with pytest.raises(ValidationFailedError):
        await after_switch.make_customer(who, lead_id, client_id, None)
    assert fake_erp.calls == []


def _lead_service(
    sessions: async_sessionmaker[AsyncSession], mode: BackofficeMode | None
) -> LeadService:
    async def provider() -> BackofficeMode:
        assert mode is not None
        return mode

    return LeadService(
        sessions,
        SettingsService(sessions, ttl_s=0),
        LeadMessenger(sessions, FakeSender()),
        backoffice_mode=provider if mode is not None else None,
    )


# I-12: матрица режим × итог. Без провайдера режима (старые стенды) — local.
@pytest.mark.parametrize(
    ("mode", "outcome", "allowed"),
    [
        (None, "won", True),
        (BackofficeMode.LOCAL, "won", True),
        (BackofficeMode.LOCAL, "lost", True),
        (BackofficeMode.ERP, "won", False),
        (BackofficeMode.ERP, "lost", True),
    ],
)
async def test_closing_won_is_forbidden_in_erp_mode_on_the_backend(
    sessions: async_sessionmaker[AsyncSession],
    mode: BackofficeMode | None,
    outcome: str,
    allowed: bool,
) -> None:
    account, _ = await make_user(sessions, "manager9@example.com", ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(session, assigned_user_id=account.id)
    leads = _lead_service(sessions, mode)

    if allowed:
        await leads.close(who, lead_id, outcome, None)  # type: ignore[arg-type]
        expected = outcome
    else:
        with pytest.raises(ConflictError) as exc_info:
            await leads.close(who, lead_id, outcome, None)  # type: ignore[arg-type]
        assert exc_info.value.details["reason"] == Reason.WON_DECIDED_BY_ERP.value
        expected = "in_progress"  # лид остался в работе, сделка не закрыта

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.stage == expected
