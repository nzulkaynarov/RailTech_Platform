"""Интеграционные тесты передачи лида/клиента в бэк-офис ERP (M3-CRM-03, ADR-0022; FIX-31).

Передача — задача после коммита клиента (FIX-31): «Сделать клиентом» коммитит клиента и стадию лида
и ставит задачу; `ErpHandoffService.run` зовёт ERP и пишет итог в `clients.erp_handoff_*`.
Проверки: клиент коммитится ДО постановки, ошибка ERP не откатывает клиента, постоянная ошибка
(409 `INN_CONFLICT`) не повторяется, временная повторяется и на последней попытке становится
`failed`, ключ идемпотентности один на все попытки, повтор после сбоя (resync) идёт тем же путём,
заявку не теряет и не задваивает; режим `local` как прежде.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.erp_handoff import ENQUEUE_FAILED
from app.domain.errors import (
    ConflictError,
    ErpRateLimitedError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.domain.stages import Stage
from app.integrations.erp import HandoffPayload, HandoffResult
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact
from app.models.deals import Deal
from app.models.leads import Lead, TelegramIdentity
from app.security.principal import Principal
from app.services.clients import ClientService
from app.services.erp_handoff import ErpHandoffService
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
        error: Exception | None = None,
    ) -> None:
        self.company_id = company_id
        self.request_id = request_id
        self.error = error
        self.calls: list[HandoffPayload] = []
        self.keys: list[str | None] = []

    async def handoff_client(
        self, payload: HandoffPayload, *, idempotency_key: str | None = None
    ) -> HandoffResult:
        self.calls.append(payload)
        self.keys.append(idempotency_key)
        if self.error is not None:
            raise self.error
        return HandoffResult(
            erp_company_id=self.company_id,
            erp_request_id=self.request_id,
            invite_sent_via=["email"],
            cabinet_url="https://cabinet.internal/magic/1",
        )


def erp_down() -> Exception:
    return UpstreamUnavailableError("erp down", reason=Reason.ERP_UNAVAILABLE)


def inn_conflict() -> Exception:
    return ConflictError("inn belongs to another client", reason=Reason.ERP_INN_CONFLICT)


class Queue:
    """Подставная очередь: запоминает постановки и видит, закоммичен ли уже клиент."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, fail: bool = False) -> None:
        self._sessions = sessions
        self.fail = fail
        self.calls: list[tuple[int, int, int]] = []
        self.committed_at_enqueue: list[tuple[bool, str | None]] = []

    async def __call__(self, client_id: int, lead_id: int, user_id: int) -> None:
        async with self._sessions() as session:  # другая сессия: видит только закоммиченное
            client = await session.get(Client, client_id)
            lead = await session.get(Lead, lead_id)
            self.committed_at_enqueue.append(
                (
                    client is not None and lead is not None and lead.client_id == client_id,
                    lead.stage if lead else None,
                )
            )
        if self.fail:
            raise RuntimeError("queue is down")
        self.calls.append((client_id, lead_id, user_id))


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


async def _erp_mode() -> BackofficeMode:
    return BackofficeMode.ERP


def _service(
    sessions: async_sessionmaker[AsyncSession], queue: Queue | None, *, erp: bool = True
) -> ClientService:
    if erp:
        return ClientService(sessions, backoffice_mode=_erp_mode, erp_handoff_enqueue=queue)
    return ClientService(sessions, erp_handoff_enqueue=queue)


async def _manager(
    sessions: async_sessionmaker[AsyncSession],
    email: str,
    *,
    stage: str = "in_progress",
    **lead: object,
) -> tuple[Principal, int]:
    account, _ = await make_user(sessions, email, ["manager"])
    who = Principal(account.id, "Менеджер", ("manager",))
    async with sessions() as session, session.begin():
        lead_id = await _create_lead(
            session,
            stage=stage,
            assigned_user_id=account.id,
            **lead,  # type: ignore[arg-type]
        )
    return who, lead_id


async def _client(sessions: async_sessionmaker[AsyncSession], client_id: int) -> Client:
    async with sessions() as session:
        client = await session.get(Client, client_id)
    assert client is not None
    return client


async def test_make_customer_commits_client_first_and_hands_off_by_task(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager1@example.com")
    queue = Queue(sessions)

    client_id = await _service(sessions, queue).make_customer(
        who, lead_id, client_id=None, new_name="ООО Логистик Плюс"
    )

    # Клиент и стадия лида зафиксированы ДО постановки задачи (другая сессия их уже видит).
    assert queue.committed_at_enqueue == [(True, "customer")]
    assert queue.calls == [(client_id, lead_id, who.user_id)]
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("pending", None)
    assert client.erp_company_id is None, "ERP ещё не вызвана: звонка внутри транзакции нет"
    assert client.erp_handoff_request is True
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.owner_mode, lead.client_id) == ("customer", "bot", client_id)
        assert (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).first() is None


async def test_task_hands_client_to_erp_and_mirrors_the_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager1b@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "ООО Логистик Плюс"
    )
    fake_erp = FakeErpClient(company_id=55, request_id=77)

    outcome = await ErpHandoffService(sessions, fake_erp).run(client_id, lead_id, who.user_id)

    assert outcome == "done"
    (call,) = fake_erp.calls
    assert (call.crm_client_id, call.crm_lead_id, call.create_request) == (client_id, lead_id, True)
    assert call.company.name == "ООО Логистик Плюс"
    assert call.contacts[0].telegram_user_id == 77001
    assert call.owner.crm_user_id == who.user_id
    client = await _client(sessions, client_id)
    assert (client.erp_company_id, client.erp_handoff_status, client.erp_handoff_error) == (
        55,
        "done",
        None,
    )
    assert client.erp_handoff_request is False
    async with sessions() as session:
        deal = (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).one()
        assert (deal.erp_deal_id, deal.external_stage, deal.client_id) == (77, "request", client_id)
        contact = (
            await session.scalars(select(ClientContact).where(ClientContact.client_id == client_id))
        ).one()
        assert (contact.is_primary, contact.full_name) == (True, "ООО Логистик Плюс")
        actions = (await session.scalars(select(AuditLog.action))).all()
        assert "client.erp_handoff_done" in actions


async def test_second_run_of_a_finished_handoff_does_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager1c@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Один")
    fake_erp = FakeErpClient()
    service = ErpHandoffService(sessions, fake_erp)

    assert await service.run(client_id, lead_id, who.user_id) == "done"
    assert await service.run(client_id, lead_id, who.user_id) == "skipped"
    assert len(fake_erp.calls) == 1
    async with sessions() as session:
        assert len((await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).all()) == 1


async def test_request_created_event_before_the_answer_does_not_duplicate_the_deal(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ERP шлёт `request.created` раньше ответа задачи: зеркало уже есть — второй сделки нет."""
    who, lead_id = await _manager(sessions, "manager1d@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Гонка")
    async with sessions() as session, session.begin():
        session.add(
            Deal(client_id=client_id, lead_id=lead_id, title="Заявка", stage="open", erp_deal_id=77)
        )

    await ErpHandoffService(sessions, FakeErpClient(request_id=77)).run(
        client_id, lead_id, who.user_id
    )

    async with sessions() as session:
        deals = (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).all()
        assert [d.erp_deal_id for d in deals] == [77]


async def test_open_deal_already_bound_to_another_erp_request_is_not_overwritten(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Открытая сделка с чужим `erp_deal_id` остаётся как есть; заявка передачи — новая сделка."""
    who, lead_id = await _manager(sessions, "manager1e@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "Занято"
    )
    async with sessions() as session, session.begin():
        session.add(
            Deal(
                client_id=client_id, lead_id=lead_id, title="Прежняя", stage="open", erp_deal_id=11
            )
        )

    await ErpHandoffService(sessions, FakeErpClient(request_id=77)).run(
        client_id, lead_id, who.user_id
    )

    async with sessions() as session:
        deals = (
            await session.scalars(select(Deal).where(Deal.lead_id == lead_id).order_by(Deal.id))
        ).all()
        assert [(d.title, d.erp_deal_id) for d in deals] == [("Прежняя", 11), (deals[1].title, 77)]
        assert deals[1].client_id == client_id
        assert deals[1].external_stage == "request"


async def test_erp_failure_does_not_roll_back_the_client_and_is_retried_then_failed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "Сбойная Компания"
    )
    fake_erp = FakeErpClient(error=erp_down())
    service = ErpHandoffService(sessions, fake_erp)

    with pytest.raises(UpstreamUnavailableError):  # не последняя попытка: Procrastinate повторит
        await service.run(client_id, lead_id, who.user_id)
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("pending", "erp_unavailable")

    with pytest.raises(UpstreamUnavailableError):  # последняя попытка: итог — ошибка в карточке
        await service.run(client_id, lead_id, who.user_id, final_attempt=True)
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("failed", "erp_unavailable")
    # Клиент и стадия лида на месте: сбой ERP ничего не откатил.
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.client_id) == ("customer", client_id)
    # Все попытки — один и тот же ключ идемпотентности: ERP, уже создавший компанию, ответит тем же.
    assert len(set(fake_erp.keys)) == 1
    assert fake_erp.keys[0] is not None


async def test_erp_rate_limit_is_transient_and_keeps_the_card_pending_until_the_last_attempt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """429 ERP (шов 0.3.0): не отказ, задача повторится после `Retry-After`; карточка «в пути»."""
    who, lead_id = await _manager(sessions, "manager429@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "Лимитная Компания"
    )
    fake_erp = FakeErpClient(error=ErpRateLimitedError(45))
    service = ErpHandoffService(sessions, fake_erp)

    with pytest.raises(ErpRateLimitedError):
        await service.run(client_id, lead_id, who.user_id)
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("pending", "erp_rate_limited")

    fake_erp.error = None  # лимит снят: повтор доходит и передаёт клиента
    fake_erp.company_id = 66
    assert await service.run(client_id, lead_id, who.user_id) == "done"
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_company_id) == ("done", 66)
    assert len(set(fake_erp.keys)) == 1, "повтор после 429 идёт с тем же ключом идемпотентности"


async def test_inn_conflict_is_permanent_shown_to_manager_and_not_retried(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2b@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Дубль")
    fake_erp = FakeErpClient(error=inn_conflict())

    outcome = await ErpHandoffService(sessions, fake_erp).run(client_id, lead_id, who.user_id)

    assert outcome == "failed"  # не исключение: Procrastinate не повторяет
    assert len(fake_erp.calls) == 1
    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("failed", "erp_inn_conflict")
    assert client.erp_company_id is None
    async with sessions() as session:
        failed = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "client.erp_handoff_failed")
            )
        ).one()
        assert failed.after is not None
        assert failed.after["code"] == "erp_inn_conflict"


async def test_validation_error_from_erp_is_permanent_too(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2c@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "Плохая"
    )
    error = ValidationFailedError("erp validation error", reason=Reason.ERP_BAD_RESPONSE)

    outcome = await ErpHandoffService(sessions, FakeErpClient(error=error)).run(
        client_id, lead_id, who.user_id
    )

    assert outcome == "failed"
    assert (await _client(sessions, client_id)).erp_handoff_error == "erp_bad_response"


async def test_connector_not_configured_is_retried_not_final(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2d@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Позже")
    error = ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)

    with pytest.raises(ConflictError):
        await ErpHandoffService(sessions, FakeErpClient(error=error)).run(
            client_id, lead_id, who.user_id
        )

    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == (
        "pending",
        "erp_not_configured",
    )


async def test_failed_enqueue_is_recorded_on_the_client_and_nothing_is_lost(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2e@example.com")

    client_id = await _service(sessions, Queue(sessions, fail=True)).make_customer(
        who, lead_id, None, "Очередь Лежит"
    )

    client = await _client(sessions, client_id)
    assert (client.erp_handoff_status, client.erp_handoff_error) == ("failed", ENQUEUE_FAILED)
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.client_id) == ("customer", client_id)


async def test_retry_after_failure_goes_the_same_way_with_the_same_key_and_keeps_the_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Повтор «Передать» после ошибки: тот же путь (задача после коммита), заявка не теряется."""
    who, lead_id = await _manager(sessions, "manager2f@example.com")
    queue = Queue(sessions)
    service = _service(sessions, queue)
    client_id = await service.make_customer(who, lead_id, None, "Повтор")
    fake_erp = FakeErpClient(error=inn_conflict())
    handoff = ErpHandoffService(sessions, fake_erp)
    assert await handoff.run(client_id, lead_id, who.user_id) == "failed"

    # Менеджер исправил ИНН в карточке и нажал «Повторить передачу».
    fake_erp.error = None
    again = await service.make_customer(who, lead_id, client_id, None)

    assert again == client_id
    assert queue.calls == [(client_id, lead_id, who.user_id)] * 2
    assert queue.committed_at_enqueue == [(True, "customer")] * 2
    assert (await _client(sessions, client_id)).erp_handoff_status == "pending"
    assert await handoff.run(client_id, lead_id, who.user_id) == "done"
    assert fake_erp.calls[-1].create_request is True, "заявка из первой попытки не потеряна"
    async with sessions() as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
        assert actions.count("lead.make_customer") == 1
        assert actions.count("client.erp_handoff") == 1
        assert len((await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).all()) == 1


async def test_same_content_gives_the_same_key_on_manual_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2g@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Ключ")
    fake_erp = FakeErpClient(error=erp_down())
    handoff = ErpHandoffService(sessions, fake_erp)
    for _ in range(2):
        with pytest.raises(UpstreamUnavailableError):
            await handoff.run(client_id, lead_id, who.user_id)

    assert fake_erp.keys[0] == fake_erp.keys[1]


async def test_make_customer_without_task_queue_is_rejected_as_not_configured(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager2h@example.com")

    with pytest.raises(ConflictError) as exc_info:
        await _service(sessions, None).make_customer(who, lead_id, None, "Без Очереди")

    assert exc_info.value.details["reason"] == Reason.ERP_NOT_CONFIGURED.value
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.client_id) == ("in_progress", None)


async def test_make_customer_local_mode_preserves_legacy_behavior(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager3@example.com", stage="won")
    queue = Queue(sessions)

    client_id = await _service(sessions, queue, erp=False).make_customer(
        who, lead_id, client_id=None, new_name="Локал Клиент"
    )

    assert queue.calls == []  # в режиме local ERP не вызывается и задачи нет
    client = await _client(sessions, client_id)
    assert (client.erp_company_id, client.erp_handoff_status) == (None, None)
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.stage == Stage.CUSTOMER.value


async def test_consent_goes_to_erp_exactly_as_the_lead_gave_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """I-13: время и версия — из лида, не «сейчас» и не «1.0»."""
    who, lead_id = await _manager(sessions, "manager4@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(
        who, lead_id, None, "Согласная Компания"
    )
    fake_erp = FakeErpClient()

    await ErpHandoffService(sessions, fake_erp).run(client_id, lead_id, who.user_id)

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
    """I-13: согласия нет — 422 менеджеру, задачи и ERP нет, в CRM ничего не меняется."""
    who, lead_id = await _manager(
        sessions, "manager5@example.com", consent_at=consent_at, consent_version=consent_version
    )
    queue = Queue(sessions)

    with pytest.raises(ValidationFailedError) as exc_info:
        await _service(sessions, queue).make_customer(
            who, lead_id, client_id=None, new_name="Без Согласия"
        )

    assert exc_info.value.details["reason"] == Reason.HANDOFF_NO_CONSENT.value
    assert queue.calls == []
    async with sessions() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert (lead.stage, lead.client_id) == ("in_progress", None)
        assert (
            await session.scalars(select(Client).where(Client.name == "Без Согласия"))
        ).first() is None


async def test_consent_withdrawn_before_the_task_runs_fails_the_handoff_without_calling_erp(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(sessions, "manager5b@example.com")
    client_id = await _service(sessions, Queue(sessions)).make_customer(who, lead_id, None, "Отзыв")
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.consent_given_at = None
    fake_erp = FakeErpClient()

    outcome = await ErpHandoffService(sessions, fake_erp).run(client_id, lead_id, who.user_id)

    assert outcome == "failed"
    assert fake_erp.calls == []
    assert (await _client(sessions, client_id)).erp_handoff_error == "handoff_no_consent"


async def test_local_mode_does_not_need_consent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Без коннектора ERP согласие никуда не передаётся — поведение режима local как было."""
    who, lead_id = await _manager(
        sessions, "manager6@example.com", stage="won", consent_at=None, consent_version=None
    )

    client_id = await ClientService(sessions).make_customer(
        who, lead_id, None, "Локал Без Согласия"
    )

    assert client_id > 0


async def test_client_made_in_local_mode_is_handed_to_erp_after_switch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """I-14: стал клиентом в режиме local, потом подключили ERP — повторная передача доходит."""
    who, lead_id = await _manager(sessions, "manager7@example.com", stage="won")
    fake_erp = FakeErpClient(company_id=61, request_id=62)

    local_client_id = await ClientService(sessions).make_customer(
        who, lead_id, None, "Клиент До ERP"
    )
    assert fake_erp.calls == []  # режим local: ERP не вызывается
    assert (await _client(sessions, local_client_id)).erp_company_id is None

    # Менеджер снова ведёт лида (повторная сделка) — повторная передача его не сбрасывает.
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.owner_mode, lead.assigned_user_id = "human", who.user_id
        lead.snoozed_until = datetime(2030, 1, 1, tzinfo=UTC)
    async with sessions() as session:
        deals_before = len((await session.scalars(select(Deal))).all())

    queue = Queue(sessions)
    after_switch = _service(sessions, queue)
    again = await after_switch.make_customer(who, lead_id, local_client_id, None)

    assert again == local_client_id
    assert queue.calls == [
        (local_client_id, lead_id, who.user_id)
    ]  # тем же путём: задача после коммита
    assert (
        await ErpHandoffService(sessions, fake_erp).run(local_client_id, lead_id, who.user_id)
        == "done"
    )
    assert len(fake_erp.calls) == 1
    assert fake_erp.calls[0].crm_client_id == local_client_id
    assert fake_erp.calls[0].create_request is False  # заявку закрыли в local, новую не заводим
    async with sessions() as session:
        client = await session.get(Client, local_client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        assert (client.erp_company_id, client.erp_handoff_status) == (61, "done")
        assert lead is not None
        assert lead.stage == "customer"
        assert lead.owner_mode == "human"
        assert lead.snoozed_until is not None
        # Зеркало сделок то же: вторая сделка не заведена.
        assert len((await session.scalars(select(Deal))).all()) == deals_before
        actions = (await session.scalars(select(AuditLog.action))).all()
        assert actions.count("lead.make_customer") == 1
        assert actions.count("client.erp_handoff") == 1

    # Клиент уже в ERP — следующая передача ничего не ставит.
    await after_switch.make_customer(who, lead_id, local_client_id, None)
    assert len(queue.calls) == 1


async def test_resync_without_consent_is_rejected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who, lead_id = await _manager(
        sessions, "manager8@example.com", stage="won", consent_at=None, consent_version=None
    )
    client_id = await ClientService(sessions).make_customer(who, lead_id, None, "Старый Клиент")
    queue = Queue(sessions)

    with pytest.raises(ValidationFailedError):
        await _service(sessions, queue).make_customer(who, lead_id, client_id, None)
    assert queue.calls == []


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
