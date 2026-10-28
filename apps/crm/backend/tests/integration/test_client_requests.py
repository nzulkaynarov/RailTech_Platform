"""«Создать заявку» (CRM-03, W16-D1-2) и статус лида для Платформы (CRM-02) на настоящей БД.

Действие из разных стадий лида и из клиента, без e-mail, без согласия — отказ, контакт без канала —
отказ; задача после коммита передаёт клиента в ERP (если его там нет) и создаёт заявку с полями
«Создать заявку»; событие `request.created` связывает зеркало с заявкой CRM по `crm_request_id`;
фильтр `platform_status` в SQL совпадает с доменной функцией.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import HandoffPayload, HandoffResult, InviteResult
from app.integrations.erp_requests import ClientRequestPayload, ClientRequestResult
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.repositories import crm
from app.schemas.client_requests import RequestCreate
from app.security.principal import Principal
from app.services.client_requests import ClientRequestService
from app.services.erp_handoff import ErpHandoffService
from app.services.erp_requests import ErpRequestService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration

CONSENT_AT = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
LETTER = uuid.UUID("3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69")


class Queue:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    async def __call__(self, deal_id: int, client_id: int, user_id: int) -> None:
        self.calls.append((deal_id, client_id, user_id))


class FakeHandoff:
    def __init__(self, company_id: int = 501) -> None:
        self.company_id = company_id
        self.calls: list[HandoffPayload] = []

    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult:
        self.calls.append(payload)
        return HandoffResult(self.company_id, None, ["telegram"], "https://cabinet.example.test")

    async def invite_client(
        self, crm_client_id: int, channel: str, crm_contact_id: int | None
    ) -> InviteResult:
        raise AssertionError("«Создать заявку» не приглашает повторно")


class FakeRequests:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[ClientRequestPayload] = []

    async def create_client_request(self, payload: ClientRequestPayload) -> ClientRequestResult:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return ClientRequestResult(erp_company_id=501, erp_request_id=9001, number="ЗВ-2026-104")


async def _erp() -> BackofficeMode:
    return BackofficeMode.ERP


async def _local() -> BackofficeMode:
    return BackofficeMode.LOCAL


def _service(
    sessions: async_sessionmaker[AsyncSession], queue: Queue | None = None
) -> ClientRequestService:
    return ClientRequestService(sessions, backoffice_mode=_erp, enqueue=queue or Queue())


async def _lead(
    sessions: async_sessionmaker[AsyncSession],
    *,
    stage: str = "handoff",
    owner: int | None = None,
    consent: bool = True,
    source: str = "telegram",
    tg_user_id: int = 88001,
) -> int:
    async with sessions() as session, session.begin():
        lead = Lead(
            display_name="Алишер",
            stage=stage,
            owner_mode="paused" if stage == "handoff" else "bot",
            assigned_user_id=owner,
            need_summary="Нужны 20 комплектов",
            product_interest=[],
            language="ru",
            source=source,
            consent_given_at=CONSENT_AT if consent else None,
            consent_version="2026-10-08" if consent else None,
        )
        session.add(lead)
        await session.flush()
        session.add(
            TelegramIdentity(tg_user_id=tg_user_id, tg_first_name="Алишер", lead_id=lead.id)
        )
        if stage == "handoff":
            session.add(
                Escalation(
                    lead_id=lead.id,
                    reason_codes=["price_or_contract_asked"],
                    priority="hot",
                    status="open",
                    sla_due_at=datetime.now(UTC) + timedelta(minutes=30),
                )
            )
        return lead.id


async def _manager(
    sessions: async_sessionmaker[AsyncSession], email: str = "rq-manager@example.com"
) -> Principal:
    account, _ = await make_user(sessions, email, ["manager"])
    return Principal(account.id, "Менеджер Заявок", ("manager",))


def _body(**changes: object) -> RequestCreate:
    data: dict[str, object] = {
        "request_key": str(uuid.uuid4()),
        "company": {"name": "ООО Пример Логистик", "inn": "301234567"},
        "contact": {"full_name": "Алишер Каримов", "use_lead_telegram": True},
        "summary": "Нужны 20 комплектов, срок — ноябрь",
        "urgency": "urgent",
        "letter_file_id": str(LETTER),
    }
    data.update(changes)
    return RequestCreate.model_validate(data)


@pytest.mark.parametrize(
    "stage", ["new", "engaged", "qualified", "handoff", "in_progress", "unresponsive", "won"]
)
async def test_request_from_any_active_stage_makes_a_client_and_a_pending_request(
    sessions: async_sessionmaker[AsyncSession], stage: str
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions, stage=stage)
    queue = Queue()

    created = await _service(sessions, queue).create_from_lead(who, lead_id, _body())

    assert queue.calls == [(created.deal_id, created.client_id, who.user_id)]
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        deal = await session.get(Deal, created.deal_id)
        client = await session.get(Client, created.client_id)
        assert lead is not None
        assert deal is not None
        assert client is not None
        assert (lead.stage, lead.client_id, lead.owner_mode) == ("customer", client.id, "bot")
        assert lead.assigned_user_id == who.user_id, "менеджер — ответственный за переписку"
        assert (client.name, client.inn) == ("ООО Пример Логистик", "301234567")
        assert deal.request_summary == "Нужны 20 комплектов, срок — ноябрь"
        assert (deal.request_urgency, deal.request_letter_file_id) == ("urgent", LETTER)
        assert (deal.erp_request_status, deal.owner_user_id, deal.lead_id) == (
            "pending",
            who.user_id,
            lead_id,
        )
        contact = await session.get(ClientContact, deal.request_contact_id)
        assert contact is not None
        assert contact.email is None, "e-mail не обязателен"
        assert contact.telegram_identity_id is not None
        assert contact.is_primary
        escalation = await session.scalar(select(Escalation).where(Escalation.lead_id == lead_id))
        if escalation is not None:
            assert (escalation.status, escalation.outcome) == ("closed", "request_created")


async def test_lost_lead_cannot_get_a_request(sessions: async_sessionmaker[AsyncSession]) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions, stage="lost")
    with pytest.raises(InvalidTransitionError) as caught:
        await _service(sessions).create_from_lead(who, lead_id, _body())
    assert caught.value.details["reason"] == Reason.REQUEST_NOT_ALLOWED


async def test_without_consent_nothing_is_created(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions, consent=False)
    queue = Queue()

    with pytest.raises(ValidationFailedError) as caught:
        await _service(sessions, queue).create_from_lead(who, lead_id, _body())

    assert caught.value.details["reason"] == Reason.HANDOFF_NO_CONSENT
    assert queue.calls == []
    async with sessions() as session:
        assert (await session.get(Lead, lead_id)).stage == "handoff"  # type: ignore[union-attr]
        assert (await session.scalars(select(Client))).first() is None


async def test_manual_lead_consent_marked_in_the_form_lets_the_request_through(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(
        sessions, stage="in_progress", owner=who.user_id, consent=False, source="phone"
    )

    created = await _service(sessions).create_from_lead(
        who,
        lead_id,
        _body(
            consent={"method": "phone", "comment": "по звонку"},
            contact={"full_name": "Иван", "phone": "+998901112233"},
        ),
    )

    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.consent_given_at is not None
        assert lead.consent_method == "phone"
        assert lead.stage == "customer"
        assert created.lead_id == lead_id


async def test_telegram_lead_consent_cannot_be_marked_by_staff(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions, consent=False)
    with pytest.raises(ConflictError) as caught:
        await _service(sessions).create_from_lead(who, lead_id, _body(consent={"method": "phone"}))
    assert caught.value.details["reason"] == Reason.CONSENT_VIA_BOT


async def test_contact_without_any_channel_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions)
    with pytest.raises(ValidationFailedError) as caught:
        await _service(sessions).create_from_lead(
            who, lead_id, _body(contact={"full_name": "Без каналов"})
        )
    assert caught.value.details["reason"] == Reason.CONTACT_CHANNEL_REQUIRED


async def test_someone_elses_lead_is_forbidden(sessions: async_sessionmaker[AsyncSession]) -> None:
    owner = await _manager(sessions, "rq-owner@example.com")
    other = await _manager(sessions, "rq-other@example.com")
    lead_id = await _lead(sessions, stage="in_progress", owner=owner.user_id)
    with pytest.raises(ForbiddenError):
        await _service(sessions).create_from_lead(other, lead_id, _body())


async def test_without_erp_connector_the_request_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions)
    service = ClientRequestService(sessions, backoffice_mode=_local, enqueue=Queue())
    with pytest.raises(ConflictError) as caught:
        await service.create_from_lead(who, lead_id, _body())
    assert caught.value.details["reason"] == Reason.ERP_NOT_CONFIGURED


async def test_existing_client_and_contact_are_reused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Есть Уже", inn="309999999")
        session.add(client)
        await session.flush()
        contact = ClientContact(
            client_id=client.id, full_name="Бахтиёр", phone_e164="+998907770000"
        )
        session.add(contact)
        await session.flush()
        client_id, contact_id = client.id, contact.id
    lead_id = await _lead(sessions)

    created = await _service(sessions).create_from_lead(
        who, lead_id, _body(client_id=client_id, company=None, contact={"contact_id": contact_id})
    )

    assert created.client_id == client_id
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        assert deal is not None
        assert deal.request_contact_id == contact_id
        assert len((await session.scalars(select(Client))).all()) == 1


async def test_new_request_for_a_client_already_in_erp(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент ERP", erp_company_id=501)
        session.add(client)
        await session.flush()
        client_id = client.id
    queue = Queue()

    created = await _service(sessions, queue).create_for_client(
        who,
        client_id,
        _body(
            company=None, contact={"full_name": "Пётр", "email": "p@example.test"}, urgency="normal"
        ),
    )

    assert created.lead_id is None
    assert queue.calls == [(created.deal_id, client_id, who.user_id)]
    fake = FakeRequests()
    outcome = await ErpRequestService(
        sessions, fake, ErpHandoffService(sessions, FakeHandoff())
    ).run(created.deal_id, who.user_id)
    assert outcome == "done"
    (call,) = fake.calls
    assert (call.crm_client_id, call.crm_request_id, call.urgency, call.letter_file_id) == (
        client_id,
        created.deal_id,
        "normal",
        LETTER,
    )
    assert call.contact is not None
    assert call.contact.email == "p@example.test"


async def test_task_hands_off_a_new_client_first_and_then_creates_the_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    lead_id = await _lead(sessions)
    created = await _service(sessions).create_from_lead(who, lead_id, _body())
    handoff, requests = FakeHandoff(), FakeRequests()

    outcome = await ErpRequestService(sessions, requests, ErpHandoffService(sessions, handoff)).run(
        created.deal_id, who.user_id
    )

    assert outcome == "done"
    (passed,) = handoff.calls
    assert passed.create_request is False, "заявку создаёт отдельная операция шва, не передача"
    (call,) = requests.calls
    assert (call.summary, call.urgency, call.letter_file_id) == (
        "Нужны 20 комплектов, срок — ноябрь",
        "urgent",
        LETTER,
    )
    assert call.owner_crm_user_id == who.user_id, "менеджер заявки — владелец сделки ERP (B-008)"
    assert call.contact is not None
    assert call.contact.telegram_user_id == 88001
    assert call.contact.email == ""
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        client = await session.get(Client, created.client_id)
        lead = await session.get(Lead, lead_id)
        assert deal is not None
        assert client is not None
        assert lead is not None
        assert (deal.erp_deal_id, deal.erp_number, deal.erp_request_status) == (
            9001,
            "ЗВ-2026-104",
            "done",
        )
        assert client.erp_company_id == 501
        assert lead.erp_request_id == 9001


async def test_permanent_erp_error_fails_the_request_without_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент ERP", erp_company_id=501)
        session.add(client)
        await session.flush()
        client_id = client.id
    created = await _service(sessions).create_for_client(
        who, client_id, _body(company=None, contact={"full_name": "Пётр", "phone": "+998901234567"})
    )
    error = NotFoundError("erp: client is not handed off", reason=Reason.ERP_BAD_RESPONSE)

    outcome = await ErpRequestService(
        sessions, FakeRequests(error=error), ErpHandoffService(sessions, FakeHandoff())
    ).run(created.deal_id, who.user_id)

    assert outcome == "failed"
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        assert deal is not None
        assert (deal.erp_request_status, deal.erp_request_error) == (
            "failed",
            "erp_bad_response",
        )


async def test_transient_erp_error_is_retried_and_failed_on_the_last_attempt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент ERP", erp_company_id=501)
        session.add(client)
        await session.flush()
        client_id = client.id
    created = await _service(sessions).create_for_client(
        who, client_id, _body(company=None, contact={"full_name": "Пётр", "phone": "+998901234567"})
    )
    down = UpstreamUnavailableError("erp down", reason=Reason.ERP_UNAVAILABLE)
    service = ErpRequestService(
        sessions, FakeRequests(error=down), ErpHandoffService(sessions, FakeHandoff())
    )

    with pytest.raises(UpstreamUnavailableError):
        await service.run(created.deal_id, who.user_id)
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        assert deal is not None
        assert (deal.erp_request_status, deal.erp_request_error) == (
            "pending",
            "erp_unavailable",
        )
    with pytest.raises(UpstreamUnavailableError):
        await service.run(created.deal_id, who.user_id, final_attempt=True)
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        assert deal is not None
        assert deal.erp_request_status == "failed"


async def test_client_without_consenting_lead_cannot_be_handed_off(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Без Лида")
        session.add(client)
        await session.flush()
        client_id = client.id
    with pytest.raises(ValidationFailedError) as caught:
        await _service(sessions).create_for_client(
            who,
            client_id,
            _body(company=None, contact={"full_name": "Пётр", "phone": "+998901234567"}),
        )
    assert caught.value.details["reason"] == Reason.HANDOFF_NO_CONSENT


async def test_platform_status_filter_matches_the_domain_rule(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """CRM-02: SQL-фильтр `platform_status` и поле ответа считают одинаково; «просроченные» —
    истёкший SLA."""
    asks = await _lead(sessions, stage="handoff", tg_user_id=88101)
    fresh = await _lead(sessions, stage="new", tg_user_id=88102)
    silent = await _lead(sessions, stage="unresponsive", tg_user_id=88103)
    async with sessions() as session, session.begin():
        late = Lead(
            display_name="Ждёт",
            stage="handoff",
            owner_mode="paused",
            language="ru",
            product_interest=[],
        )
        session.add(late)
        await session.flush()
        session.add(
            Escalation(
                lead_id=late.id,
                reason_codes=["callback_requested"],
                priority="warm",
                status="open",
                sla_due_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        late_id = late.id

    async def ids(**flt: object) -> set[int]:
        async with sessions() as session:
            rows, _ = await crm.list_leads(session, crm.LeadFilter(**flt), 0, 100, 0, "created")  # type: ignore[arg-type]
        return {r.id for r in rows}

    assert await ids(platform_status="wants_quote") == {asks}
    assert await ids(platform_status="new") == {fresh}
    assert await ids(platform_status="no_answer") == {silent, late_id}
    assert await ids(platform_status="new,wants_quote") == {asks, fresh}
    assert await ids(overdue=True) == {late_id}
    assert late_id not in await ids(overdue=False)


# ── Идемпотентность «Создать заявку» (`request_key` формы) ─────────────────────────────────────


async def _requests_of(sessions: async_sessionmaker[AsyncSession], key: uuid.UUID) -> list[Deal]:
    async with sessions() as session:
        return list((await session.scalars(select(Deal).where(Deal.request_key == key))).all())


async def test_repeat_with_the_same_request_key_returns_the_same_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Двойной клик или повтор по таймауту: та же заявка (`created = False`), без второй строки и
    задачи."""
    who = await _manager(sessions)
    lead_id = await _lead(sessions)
    queue = Queue()
    body = _body()

    first = await _service(sessions, queue).create_from_lead(who, lead_id, body)
    again = await _service(sessions, queue).create_from_lead(who, lead_id, body)

    assert first.created
    assert not again.created
    assert again.deal_id == first.deal_id
    assert len(queue.calls) == 1, "вторая задача в ERP не ставится — второго письма ВХ не будет"
    assert len(await _requests_of(sessions, body.request_key)) == 1


async def test_parallel_submissions_with_one_request_key_make_one_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Две одновременные отправки формы: одна заявка и одна задача. Мутационная проверка (описание
    PR): без блокировки лида и UNIQUE `deals.request_key` тест красный (две заявки), с ними —
    зелёный."""
    who = await _manager(sessions)
    lead_id = await _lead(sessions)
    queue = Queue()
    body = _body()

    results = await asyncio.gather(
        _service(sessions, queue).create_from_lead(who, lead_id, body),
        _service(sessions, queue).create_from_lead(who, lead_id, body),
    )

    assert {r.deal_id for r in results} == {results[0].deal_id}
    assert sorted(r.created for r in results) == [False, True]
    assert len(queue.calls) == 1
    assert len(await _requests_of(sessions, body.request_key)) == 1


async def test_repeat_for_a_client_with_the_same_request_key_returns_the_same_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент ERP", erp_company_id=501)
        session.add(client)
        await session.flush()
        client_id = client.id
    queue = Queue()
    body = _body(company=None, contact={"full_name": "Пётр", "phone": "+998901234567"})

    results = await asyncio.gather(
        _service(sessions, queue).create_for_client(who, client_id, body),
        _service(sessions, queue).create_for_client(who, client_id, body),
    )

    assert {r.deal_id for r in results} == {results[0].deal_id}
    assert len(queue.calls) == 1


async def test_request_key_of_another_lead_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _manager(sessions)
    first_lead = await _lead(sessions, tg_user_id=88201)
    second_lead = await _lead(sessions, tg_user_id=88202)
    body = _body()
    await _service(sessions).create_from_lead(who, first_lead, body)

    with pytest.raises(ConflictError) as caught:
        await _service(sessions).create_from_lead(who, second_lead, body)

    assert caught.value.details["reason"] == Reason.REQUEST_KEY_REUSED


async def test_erp_idempotency_conflict_fails_the_request_without_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ERP: тот же ключ шва с другим телом (409) — заявка `failed` с причиной, без автоповтора."""
    who = await _manager(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Клиент ERP", erp_company_id=501)
        session.add(client)
        await session.flush()
        client_id = client.id
    created = await _service(sessions).create_for_client(
        who, client_id, _body(company=None, contact={"full_name": "Пётр", "phone": "+998901234567"})
    )
    conflict = ConflictError("ERP: заявка уже отправлялась", reason=Reason.ERP_REQUEST_CONFLICT)

    outcome = await ErpRequestService(
        sessions, FakeRequests(error=conflict), ErpHandoffService(sessions, FakeHandoff())
    ).run(created.deal_id, who.user_id)

    assert outcome == "failed"
    async with sessions() as session:
        deal = await session.get(Deal, created.deal_id)
        assert deal is not None
        assert (deal.erp_request_status, deal.erp_request_error) == (
            "failed",
            "erp_request_conflict",
        )


async def test_request_key_is_unique_in_the_database(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Последний рубеж идемпотентности — UNIQUE `deals.request_key`. Мутационная проверка (описание
    PR): без уникального индекса тест красный."""
    from sqlalchemy.exc import IntegrityError

    key = uuid.uuid4()
    async with sessions() as session, session.begin():
        session.add(Deal(title="Первая", stage="open", request_key=key))
    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            session.add(Deal(title="Вторая", stage="open", request_key=key))


async def test_leads_are_filtered_by_channel(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Фильтр «канал» экрана «Лиды» (W16-D1-2b): `source` CRM, несколько через запятую."""
    tg = await _lead(sessions, stage="new", tg_user_id=88301)
    async with sessions() as session, session.begin():
        web = Lead(
            display_name="С сайта", stage="new", owner_mode="bot", language="ru", source="web"
        )
        session.add(web)
        await session.flush()
        web_id = web.id

    async def ids(source: str) -> set[int]:
        async with sessions() as session:
            rows, _ = await crm.list_leads(
                session, crm.LeadFilter(source=source), 0, 100, 0, "created"
            )
        return {r.id for r in rows}

    assert await ids("web") == {web_id}
    assert await ids("telegram") == {tg}
    assert await ids("telegram,web") == {tg, web_id}
