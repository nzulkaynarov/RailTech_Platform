"""ТЕСТ-1: тестовые компании (отметка из ERP) не попадают в рабочие списки, счётчики и панели.

Клиент с `is_test` уходит из списка клиентов (виден по `test=only`), его лиды — из реестра,
«Входящих» и воронки, сделки — из общего списка и сводки; по `client_id` сделки видны.
Ничего не удаляется.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.deals import deal_rows, filtered
from app.models.clients import Client, ServiceRequest
from app.models.deals import Deal
from app.models.leads import Lead
from app.repositories import clients as clients_repo
from app.repositories import lead_visibility, service_requests
from app.services import deals
from app.services.dashboard import _funnel

pytestmark = pytest.mark.integration


async def seed(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Рабочий и тестовый клиент: у каждого лид, открытая сделка и сервисный запрос."""
    ids: dict[str, int] = {}
    async with sessions() as session, session.begin():
        for key, test in (("real", False), ("fake", True)):
            client = Client(name=f"Клиент {key}", is_test=test)
            session.add(client)
            await session.flush()
            lead = Lead(
                display_name=key,
                stage="customer",
                owner_mode="bot",
                client_id=client.id,
                language="ru",
            )
            session.add(lead)
            await session.flush()
            session.add(
                Deal(title=f"Сделка {key}", client_id=client.id, lead_id=lead.id, stage="open")
            )
            session.add(ServiceRequest(client_id=client.id, lead_id=lead.id, summary="Вопрос"))
            ids[key] = client.id
            ids[f"{key}_lead"] = lead.id
    return ids


async def test_the_client_list_hides_test_companies_unless_asked(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    async with sessions() as session:
        shown = {c.id for c, _, _ in await clients_repo.list_with_stats(session, None, 100)}
        only = {c.id for c, _, _ in await clients_repo.list_with_stats(session, None, 100, "only")}
        both = {c.id for c, _, _ in await clients_repo.list_with_stats(session, None, 100, "all")}
    assert shown == {ids["real"]}
    assert only == {ids["fake"]}
    assert both == {ids["real"], ids["fake"]}


async def test_leads_funnel_and_service_requests_skip_test_companies(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    async with sessions() as session:
        working = set(await session.scalars(select(Lead.id).where(lead_visibility.working())))
        listed = set(await session.scalars(select(Lead.id).where(lead_visibility.listed())))
        funnel = await _funnel(session)
        requests = await service_requests.list_with_clients(session, "open", 50)
    assert working == {ids["real_lead"]}
    assert listed == {ids["real_lead"], ids["fake_lead"]}  # таймеры и доступ к беседе — по `listed`
    assert funnel == {"customer": 1}
    assert [name for _, name in requests] == ["Клиент real"]


async def test_deal_list_and_summary_skip_test_companies_but_the_card_keeps_them(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    ids = await seed(sessions)
    async with sessions() as session:
        common = await deal_rows(session, filtered(None, None, None, None, None))
        card = await deal_rows(session, filtered(None, None, ids["fake"], None, None))
        report = await deals.summary(session, 30, _now())
        total = await session.scalar(select(func.count()).select_from(Deal))
    assert [d.client_id for d in common] == [ids["real"]]
    assert [d.client_id for d in card] == [
        ids["fake"]
    ]  # карточка тестового клиента показывает свои сделки
    assert report.open_count == 1
    assert total == 2  # ничего не удалено


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
