"""«Кто это?» в карточке лида (ЛП-1): «Партнёр» вместо «Клиента» и один клиент на повторное нажатие.

Партнёр: заявка кандидата в ERP (источник «лид»), лид — исход «передан как партнёр», в `customer`
не попадает; повтор и параллельный повтор — первая заявка, без второй. Клиент: компания ищется по
ИНН, затем по названию и стране, повтор формы — та же заявка; второй карточки компании нет.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.errors import InvalidTransitionError, UpstreamUnavailableError
from app.integrations.erp_partner import PartnerApplicationPayload, PartnerApplicationResult
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.schemas.client_requests import RequestCreate
from app.schemas.partner_handoff import PartnerHandoffIn
from app.security.principal import Principal
from app.services.client_requests import ClientRequestService
from app.services.partner_handoff import PartnerHandoffService
from tests.integration.crm_helpers import make_user
from tests.integration.roles_helpers import audit_rows

pytestmark = pytest.mark.integration

LETTER = uuid.UUID("3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69")


class FakeErpPartners:
    """Как ERP: идемпотентна по номеру лида — вторая заявка того же лида возвращает первую."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[PartnerApplicationPayload] = []
        self._by_lead: dict[str, int] = {}

    async def create_partner_application(
        self, payload: PartnerApplicationPayload
    ) -> PartnerApplicationResult:
        self.calls.append(payload)
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        known = self._by_lead.get(payload.lead_number)
        if known is not None:
            return PartnerApplicationResult(known, "submitted", False)
        self._by_lead[payload.lead_number] = 7000 + len(self._by_lead)
        return PartnerApplicationResult(self._by_lead[payload.lead_number], "submitted", True)


async def _erp() -> BackofficeMode:
    return BackofficeMode.ERP


async def _local() -> BackofficeMode:
    return BackofficeMode.LOCAL


class Queue:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    async def __call__(self, deal_id: int, client_id: int, user_id: int) -> None:
        self.calls.append((deal_id, client_id, user_id))


async def _manager(sessions: async_sessionmaker[AsyncSession]) -> Principal:
    account, _ = await make_user(sessions, "who-is-it@example.com", ["manager"])
    return Principal(account.id, "Менеджер", ("manager",))


async def _lead(sessions: async_sessionmaker[AsyncSession], *, source: str = "email") -> int:
    async with sessions() as session, session.begin():
        lead = Lead(
            display_name="Иван Партнёров",
            stage="new",
            owner_mode="paused",
            need_summary="Поставляем крепёж",
            product_interest=[],
            language="ru",
            source=source,
            email="ivan@partner.example",
            consent_given_at=datetime(2026, 11, 20, tzinfo=UTC),
            consent_version="2026-10-08",
        )
        session.add(lead)
        await session.flush()
        session.add(Escalation(lead_id=lead.id, reason_codes=["x"], priority="hot", status="open"))
        return lead.id


def _partner_body(**changes: object) -> PartnerHandoffIn:
    data: dict[str, object] = {
        "company_name": "Контур Партнёр",
        "country": "uz",
        "inn": "301234567",
        "offer": "Поставляем крепёж",
        "contact_name": "Иван Партнёров",
        "email": "ivan@partner.example",
        "phone": "+998901234567",
    }
    data.update(changes)
    return PartnerHandoffIn.model_validate(data)


def _service(
    sessions: async_sessionmaker[AsyncSession], erp: FakeErpPartners
) -> PartnerHandoffService:
    return PartnerHandoffService(sessions, erp, backoffice_mode=_erp)


async def test_partner_makes_an_application_and_closes_the_lead_as_partner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id, erp = await _manager(sessions), await _lead(sessions), FakeErpPartners()

    result = await _service(sessions, erp).hand_over(who, lead_id, _partner_body())

    assert result.created
    payload = erp.calls[0]
    assert (payload.lead_number, payload.company_name, payload.country, payload.inn) == (
        f"L-{lead_id:04d}",
        "Контур Партнёр",
        "UZ",
        "301234567",
    )
    assert payload.categories_description == "Поставляем крепёж"
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.discarded_kind) == ("lost", "partner")
        assert lead.partner_application_id == result.application_id
        assert lead.client_id is None, "партнёр не становится клиентом"
        assert not await session.scalar(select(func.count()).select_from(Client))
        escalation = await session.scalar(select(Escalation).where(Escalation.lead_id == lead_id))
        assert escalation is not None
        assert escalation.outcome == "handed_over_partner"


async def test_second_press_returns_the_first_application(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id, erp = await _manager(sessions), await _lead(sessions), FakeErpPartners()
    service = _service(sessions, erp)

    first = await service.hand_over(who, lead_id, _partner_body())
    again = await service.hand_over(who, lead_id, _partner_body(company_name="Иное название"))

    assert (first.created, again.created) == (True, False)
    assert again.application_id == first.application_id
    assert len(erp.calls) == 1, "повтор не доходит до ERP: лид уже закрыт исходом «партнёр»"


async def test_concurrent_presses_make_one_application(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Mutation check (PR): without the outcome re-check under the lead lock - two records."""
    who, lead_id, erp = await _manager(sessions), await _lead(sessions), FakeErpPartners()

    results = await asyncio.gather(
        *(_service(sessions, erp).hand_over(who, lead_id, _partner_body()) for _ in range(3))
    )

    assert {r.application_id for r in results} == {results[0].application_id}
    assert len(erp._by_lead) == 1
    assert len(await audit_rows(sessions, "lead.hand_over_partner")) == 1, (
        "one hand-over in the journal"
    )
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.partner_application_id == results[0].application_id


async def test_erp_failure_leaves_the_lead_untouched_and_retry_works(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions), await _lead(sessions)
    broken = FakeErpPartners(error=UpstreamUnavailableError("down"))

    with pytest.raises(UpstreamUnavailableError):
        await _service(sessions, broken).hand_over(who, lead_id, _partner_body())

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.discarded_kind) == ("new", None)
    retried = await _service(sessions, FakeErpPartners()).hand_over(who, lead_id, _partner_body())
    assert retried.created


async def test_closed_lead_cannot_be_handed_over_as_a_partner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions), await _lead(sessions)
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.stage = "lost"
    with pytest.raises(InvalidTransitionError):
        await _service(sessions, FakeErpPartners()).hand_over(who, lead_id, _partner_body())


@pytest.mark.parametrize("source", ["web", "telegram", "email", "phone"])
async def test_every_lead_channel_takes_the_same_partner_path(
    sessions: async_sessionmaker[AsyncSession], source: str
) -> None:
    who, lead_id = await _manager(sessions), await _lead(sessions, source=source)
    result = await _service(sessions, FakeErpPartners()).hand_over(who, lead_id, _partner_body())
    assert result.created


def test_partner_form_needs_a_channel() -> None:
    with pytest.raises(ValueError, match="e-mail or phone"):
        _partner_body(email="", phone="")


# ── Клиент: одна компания — одна карточка ─────────────────────────────────────────────


def _client_service(
    sessions: async_sessionmaker[AsyncSession], queue: Queue | None = None
) -> ClientRequestService:
    return ClientRequestService(sessions, backoffice_mode=_erp, enqueue=queue or Queue())


def _request(**changes: object) -> RequestCreate:
    data: dict[str, object] = {
        "request_key": str(uuid.uuid4()),
        "company": {"name": "ООО «Пример Логистик»", "inn": "301234567"},
        "contact": {"full_name": "Алишер Каримов", "email": "a@example.test"},
        "summary": "Нужны 20 комплектов",
        "letter_file_id": str(LETTER),
    }
    data.update(changes)
    return RequestCreate.model_validate(data)


async def _clients(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(Client)) or 0)


async def test_second_press_with_a_new_key_returns_the_first_request_and_one_company(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id, queue = await _manager(sessions), await _lead(sessions), Queue()
    service = _client_service(sessions, queue)

    first = await service.create_from_lead(who, lead_id, _request())
    again = await service.create_from_lead(who, lead_id, _request())

    assert (first.created, again.created) == (True, False)
    assert (again.deal_id, again.client_id) == (first.deal_id, first.client_id)
    assert await _clients(sessions) == 1
    assert len(queue.calls) == 1


async def test_concurrent_presses_with_different_keys_make_one_company_and_one_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Мутационная проверка (PR): без поиска компании и «той же заявки» — две карточки и заявки."""
    who, lead_id, queue = await _manager(sessions), await _lead(sessions), Queue()

    results = await asyncio.gather(
        *(
            _client_service(sessions, queue).create_from_lead(who, lead_id, _request())
            for _ in range(3)
        )
    )

    assert len({r.deal_id for r in results}) == 1
    assert await _clients(sessions) == 1
    assert len(queue.calls) == 1
    async with sessions() as session:
        deals = await session.scalar(select(func.count()).select_from(Deal))
    assert deals == 1


async def test_company_is_found_by_inn_then_by_normalised_name_and_country(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, queue = await _manager(sessions), Queue()
    service = _client_service(sessions, queue)
    first_lead = await _lead(sessions)
    first = await service.create_from_lead(who, first_lead, _request())

    # другая запись названия, тот же ИНН
    by_inn = await service.create_from_lead(
        who,
        await _lead(sessions),
        _request(company={"name": "Пример-Логистик LLC", "inn": "301234567"}),
    )
    # без ИНН, то же название иначе записанное
    by_name = await service.create_from_lead(
        who,
        await _lead(sessions),
        _request(company={"name": "  ооо  пример логистик ", "inn": None, "country": "uz"}),
    )

    assert by_inn.client_id == first.client_id
    assert by_name.client_id == first.client_id
    assert await _clients(sessions) == 1


async def test_same_name_in_another_country_is_another_company(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, queue = await _manager(sessions), Queue()
    service = _client_service(sessions, queue)
    first = await service.create_from_lead(
        who,
        await _lead(sessions),
        _request(company={"name": "Рельс Трейд", "inn": None, "country": "UZ"}),
    )
    other = await service.create_from_lead(
        who,
        await _lead(sessions),
        _request(company={"name": "Рельс Трейд", "inn": None, "country": "KZ"}),
    )
    assert other.client_id != first.client_id
    assert await _clients(sessions) == 2


async def test_a_different_text_from_the_same_lead_is_a_new_request_of_the_same_company(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id, queue = await _manager(sessions), await _lead(sessions), Queue()
    service = _client_service(sessions, queue)
    first = await service.create_from_lead(who, lead_id, _request())
    second = await service.create_from_lead(who, lead_id, _request(summary="Ещё 5 комплектов"))
    assert second.created
    assert second.deal_id != first.deal_id
    assert second.client_id == first.client_id
    assert await _clients(sessions) == 1
