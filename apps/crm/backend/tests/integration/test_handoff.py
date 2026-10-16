"""Интеграционные тесты передачи лида/клиента в бэк-офис ERP (M3-CRM-03, ADR-0022).

Проверка сквозного сценария:
- Переход из in_progress в customer при backoffice_mode == 'erp'
- Создание / связывание компании (erp_company_id) и заявки (erp_deal_id, external_stage='request')
- Создание ClientContact и привязка TelegramIdentity
- Откат транзакции при сбое ERP
- Обратная совместимость в режиме 'local'
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.errors import Reason, UpstreamUnavailableError
from app.domain.stages import Stage
from app.integrations.erp import HandoffPayload, HandoffResult
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.security.principal import Principal
from app.services.clients import ClientService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration


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
