"""Надёжность обработки событий ERP на шине rt_bus, настоящая БД (FIX-33 → B4; I-9, I-10, I-11).

Проверки:
* Telegram уходит ПОСЛЕ коммита обработки и один раз на событие (повтор события, повторная задача
  и сборщик второго сообщения не шлют); откат обработки сообщений не оставляет;
* запись inbox, не взятая очередью, подбирается шиной; неотправленные сообщения — сборщиком;
* потолок неудачных обработок → `failed` (видно в центре внешних сервисов);
* сверка `client.erp_company_id` с событием: несовпадение — ошибка обработки, ничего не меняется;
  клиент без сопоставления (передача идёт) — событие применяется и сопоставление записывается;
* `deals.erp_deal_id` уникален; ответ передачи и `request.created` в любом порядке и параллельно
  дают одно зеркало;
* порядок по времени события: старое событие после нового стадию не откатывает.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from rt_bus import Event
from rt_bus.envelope import new_event
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.erp_event import parse_erp_event
from app.integrations.erp import HandoffResult
from app.models.clients import Client
from app.models.deals import Deal
from app.models.integrations import ErpEventNotice
from app.models.leads import Lead, LeadNote
from app.repositories import events as events_repo
from app.services.erp_handoff import ErpHandoffService
from tests.integration.bus_harness import (
    ERP_COMPANY,
    ERP_DEAL,
    STAGES,
    T0,
    Harness,
    data_for,
    event_type_of,
)

pytestmark = pytest.mark.integration

INBOX_AGE = (
    "UPDATE rt_bus_inbox SET next_attempt_at = :past, received_at = :past WHERE event_id = :id"
)


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Harness]:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def _due(harness: Harness, event_id: str) -> None:
    """Автоповтор «настал срок»: следующая попытка обработки — сейчас."""
    past = datetime.now(UTC) - timedelta(minutes=5)
    async with harness.sessions() as session, session.begin():
        await session.execute(text(INBOX_AGE), {"past": past, "id": uuid.UUID(event_id)})


async def _age_notice(harness: Harness, event_id: str, **delta: float) -> None:
    async with harness.sessions() as session, session.begin():
        await session.execute(
            update(ErpEventNotice)
            .where(ErpEventNotice.event_id == uuid.UUID(event_id))
            .values(created_at=datetime.now(UTC) - timedelta(**delta))
        )


# --- Telegram после коммита и один раз -----------------------------------------------------------


async def test_telegram_goes_after_the_commit_and_only_once_per_event(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    assert await harness.process(event_id) == "processed"

    assert [chat for chat, _ in harness.bot.sent] == [777]
    assert harness.bot.inbox_status_at_send == ["processed"], (
        "в момент отправки обработка уже закоммичена"
    )
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.notified_at is not None

    # Повтор той же задачи, сборщик и прямой вызов — второго сообщения нет.
    assert await harness.process(event_id) == "processed"
    assert await harness.notices.deliver(event_id) == 0
    await _age_notice(harness, event_id, minutes=5)
    assert await harness.notices.sweep() == 0
    assert len(harness.bot.sent) == 1


async def test_a_rolled_back_processing_sends_nothing_and_the_retry_sends_once(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)
    real_publish = events_repo.publish
    calls = 0

    async def flaky_publish(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("db hiccup inside the transaction")
        await real_publish(*args, **kwargs)

    monkeypatch.setattr(events_repo, "publish", flaky_publish)

    assert await harness.process(event_id) == "received", "ошибка обработчика — автоповтор"
    row = await harness.inbox(event_id)
    assert (row["status"], row["attempts"]) == ("received", 1)
    assert "db hiccup" in (row["error"] or "")
    assert harness.bot.sent == [], "из откатившейся транзакции сообщение не уходит"
    assert await harness.notice(event_id) is None
    async with harness.sessions() as session:
        assert (await session.scalars(select(LeadNote))).all() == []

    # Раньше срока автоповтор ничего не делает; в срок — обрабатывает и шлёт одно сообщение.
    assert await harness.process(event_id) == "received"
    await _due(harness, event_id)
    assert await harness.process(event_id) == "processed"
    assert len(harness.bot.sent) == 1


async def test_a_poison_event_becomes_failed_after_the_attempt_ceiling(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("always broken")

    monkeypatch.setattr(events_repo, "publish", broken)
    attempts = len(harness.bus.config.inbox_retry_delays) + 1
    for _ in range(attempts):
        await harness.process(event_id)
        await _due(harness, event_id)

    row = await harness.inbox(event_id)
    assert (row["status"], row["attempts"]) == ("failed", attempts)
    harness.enqueued.clear()
    assert await harness.bus.requeue_stuck_inbox(older_than=0) == 0
    assert harness.enqueued == [], "failed шина больше не ставит"


# --- Подбор неподобранного -----------------------------------------------------------------------


async def test_an_inbox_row_that_never_reached_the_queue_is_picked_up(harness: Harness) -> None:
    """Постановка в очередь упала → ответ 200 → запись осталась → шина ставит её заново."""
    client_id, _ = await harness.seed_client()
    harness.enqueue_error = OSError("procrastinate down")
    event_id = await harness.store("quote.sent", client_id)
    assert harness.enqueued == []
    assert (await harness.inbox(event_id))["status"] == "received"

    harness.enqueue_error = None
    assert await harness.bus.requeue_stuck_inbox(older_than=0) == 1
    assert harness.enqueued == [event_id]
    assert await harness.process(event_id) == "processed"
    assert len(harness.bot.sent) == 1


async def test_messages_left_unsent_after_a_crash_are_sent_by_the_sweeper_once(
    harness: Harness,
) -> None:
    """Воркер упал между коммитом обработки и отправкой: `notified_at` пуст, сообщение живо."""
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)

    async def crash(_: str) -> int:
        return 0  # «процесс умер» до отправки

    with patch.object(harness.bus, "_after_processed", crash):
        assert await harness.process(event_id) == "processed"
    assert harness.bot.sent == []

    await _age_notice(harness, event_id, minutes=5)
    assert await harness.notices.sweep() == 1
    assert await harness.notices.sweep() == 0
    assert len(harness.bot.sent) == 1


async def test_a_permanent_telegram_refusal_is_not_retried_but_a_network_failure_is(
    harness: Harness,
) -> None:
    from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
    from aiogram.methods import SendMessage

    client_id, _ = await harness.seed_client()
    blocked = await harness.store("quote.sent", client_id, erp_deal_id=1)
    harness.bot.fail_with = TelegramForbiddenError(SendMessage(chat_id=1, text="x"), "blocked")
    assert await harness.process(blocked) == "processed"
    notice = await harness.notice(blocked)
    assert notice is not None
    assert notice.notified_at is not None, "бот заблокирован — повторять нечего"

    flaky = await harness.store("invoice.paid", client_id, erp_deal_id=2)
    harness.bot.fail_with = TelegramNetworkError(SendMessage(chat_id=1, text="x"), "timeout")
    assert await harness.process(flaky) == "processed"
    notice = await harness.notice(flaky)
    assert notice is not None
    assert notice.notified_at is None, "сеть упала — сообщение дождётся сборщика"
    assert notice.lease_until is None

    harness.bot.fail_with = None
    await _age_notice(harness, flaky, minutes=5)
    assert await harness.notices.sweep() == 1
    assert [chat for chat, _ in harness.bot.sent] == [777]


async def test_a_partly_sent_message_is_not_sent_twice_to_the_same_chat(
    harness: Harness,
) -> None:
    """Два аккаунта клиента, один недоступен: после повтора первый второго сообщения не получает."""
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.methods import SendMessage

    from app.models.leads import TelegramIdentity

    client_id, lead_id = await harness.seed_client()
    async with harness.sessions() as session, session.begin():
        session.add(
            TelegramIdentity(
                tg_user_id=888, client_id=client_id, lead_id=lead_id, tg_first_name="B"
            )
        )
    event_id = await harness.store("quote.sent", client_id)

    sent: list[int] = []
    down = [True]
    real_send = harness.bot.send_message

    async def second_is_down(chat_id: int, text: str, **kwargs: Any) -> Any:
        if chat_id == 888 and down[0]:
            raise TelegramNetworkError(SendMessage(chat_id=1, text="x"), "down")
        sent.append(chat_id)
        return await real_send(chat_id, text, **kwargs)

    with patch.object(harness.bot, "send_message", second_is_down):
        assert await harness.process(event_id) == "processed"
        assert sorted(sent) == [777]
        down[0] = False
        await _age_notice(harness, event_id, minutes=5)
        assert await harness.notices.sweep() == 1

    assert sorted(chat for chat, _ in harness.bot.sent) == [777, 888]


# --- Сверка компании ------------------------------------------------------------------------------


async def test_a_mismatching_company_fails_the_event_and_changes_nothing(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client(erp_company_id=ERP_COMPANY)
    event_id = await harness.store("quote.sent", client_id, company_id=999)
    attempts = len(harness.bus.config.inbox_retry_delays) + 1
    for _ in range(attempts):
        await harness.process(event_id)
        await _due(harness, event_id)

    row = await harness.inbox(event_id)
    assert row["status"] == "failed"
    assert "company mismatch" in (row["error"] or "")
    assert await harness.notice(event_id) is None
    assert await harness.deals() == []
    assert harness.bot.sent == []
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id == ERP_COMPANY
        assert (await session.scalars(select(LeadNote))).all() == []


async def test_a_client_without_a_mapping_yet_accepts_the_event_and_records_the_mapping(
    harness: Harness,
) -> None:
    """Передача ещё идёт (ответ ERP не записан): событие не отклоняется, сопоставление — из него."""
    client_id, _ = await harness.seed_client(erp_company_id=None)
    event_id = await harness.store("quote.sent", client_id)

    assert await harness.process(event_id) == "processed"

    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        assert client.erp_company_id == ERP_COMPANY
    assert (await harness.inbox(event_id))["status"] == "processed"


# --- Уникальный erp_deal_id и одно зеркало --------------------------------------------------------


async def test_erp_deal_id_is_unique_in_the_database(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    async with harness.sessions() as session, session.begin():
        session.add(Deal(client_id=client_id, title="A", erp_deal_id=1))
        session.add(Deal(client_id=client_id, title="local 1"))  # NULL не конфликтует
        session.add(Deal(client_id=client_id, title="local 2"))
    with pytest.raises(IntegrityError):
        async with harness.sessions() as session, session.begin():
            session.add(Deal(client_id=client_id, title="B", erp_deal_id=1))


def _erp_answering(deal_id: int) -> Any:
    class Erp:
        async def handoff_client(self, payload: Any, *, idempotency_key: str | None = None) -> Any:
            return HandoffResult(
                erp_company_id=ERP_COMPANY,
                erp_request_id=deal_id,
                invite_sent_via=[],
                cabinet_url="https://cabinet.internal/x",
            )

    return Erp()


async def _prepare_handoff(harness: Harness, client_id: int, lead_id: int) -> None:
    async with harness.sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        lead = await session.get(Lead, lead_id)
        assert client is not None
        assert lead is not None
        lead.consent_given_at = T0
        lead.consent_version = "v1"
        client.erp_handoff_status, client.erp_handoff_request = "pending", True
        client.erp_company_id = None


async def _handoff(harness: Harness, client_id: int, lead_id: int, deal_id: int = ERP_DEAL) -> str:
    await _prepare_handoff(harness, client_id, lead_id)
    service = ErpHandoffService(harness.sessions, _erp_answering(deal_id))
    return await service.run(client_id, lead_id, None)


async def test_event_before_the_handoff_answer_converges_to_one_mirror(harness: Harness) -> None:
    """FIX-31 → FIX-33: `request.created` приходит раньше, чем задача запишет `erp_deal_id`."""
    client_id, lead_id = await harness.seed_client(erp_company_id=None)
    async with harness.sessions() as session, session.begin():
        session.add(Deal(client_id=client_id, lead_id=lead_id, title="Локальная", stage="open"))
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"
    assert await _handoff(harness, client_id, lead_id) == "done"

    (deal,) = await harness.deals()
    assert (deal.erp_deal_id, deal.lead_id, deal.client_id) == (ERP_DEAL, lead_id, client_id)
    assert deal.external_stage == "request"
    assert deal.title == "Поставка осей", "заявка ERP заняла сделку лида, а не завела вторую"


async def test_handoff_answer_before_the_event_converges_to_the_same_mirror(
    harness: Harness,
) -> None:
    client_id, lead_id = await harness.seed_client(erp_company_id=None)
    assert await _handoff(harness, client_id, lead_id) == "done"
    event_id = await harness.store("request.created", client_id)

    assert await harness.process(event_id) == "processed"

    (deal,) = await harness.deals()
    assert (deal.erp_deal_id, deal.lead_id) == (ERP_DEAL, lead_id)


async def test_event_and_handoff_racing_in_parallel_leave_exactly_one_mirror(
    harness: Harness,
) -> None:
    for round_no in range(5):
        client_id, lead_id = await harness.seed_client(erp_company_id=None, tg_user_id=None)
        deal_id = ERP_DEAL + round_no
        async with harness.sessions() as session, session.begin():
            session.add(Deal(client_id=client_id, lead_id=lead_id, title="Локальная"))
        event_id = await harness.store(
            "request.created",
            client_id,
            erp_deal_id=deal_id,
            payload={"source": "crm", "erp_request_id": deal_id},
        )
        await _prepare_handoff(harness, client_id, lead_id)

        results = await asyncio.gather(
            harness.process(event_id),
            ErpHandoffService(harness.sessions, _erp_answering(deal_id)).run(
                client_id, lead_id, None
            ),
            return_exceptions=True,
        )

        assert list(results) == ["processed", "done"], results
        async with harness.sessions() as session:
            mirrors = (await session.scalars(select(Deal).where(Deal.erp_deal_id == deal_id))).all()
            local = (await session.scalars(select(Deal).where(Deal.lead_id == lead_id))).all()
        assert len(mirrors) == 1, f"round {round_no}: {len(mirrors)} mirrors"
        assert len(local) == 1, f"round {round_no}: the lead's deal was duplicated"


# --- Порядок по времени события -------------------------------------------------------------------


async def _stage(harness: Harness) -> tuple[str | None, datetime | None, str]:
    (deal,) = await harness.deals()
    return deal.external_stage, deal.external_stage_at, deal.title


async def test_eta_changed_that_arrives_after_paid_does_not_roll_the_stage_back(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client()
    eta = await harness.store(
        "delivery.eta_changed", client_id, occurred_at=T0, title="Старое название"
    )
    paid = await harness.store(
        "invoice.paid", client_id, occurred_at=T0 + timedelta(hours=2), title="Новое название"
    )

    await harness.process(paid)  # пришло первым, хотя произошло позже
    await harness.process(eta)

    assert await _stage(harness) == ("paid", T0 + timedelta(hours=2), "Новое название")
    assert (await harness.inbox(eta))["status"] == "processed", (
        "событие записано и в ленте, зеркало не тронуто"
    )
    async with harness.sessions() as session:
        assert len((await session.scalars(select(LeadNote))).all()) == 2


async def test_a_newer_event_after_an_older_one_moves_the_stage_forward(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    first = await harness.store("quote.sent", client_id, occurred_at=T0)
    second = await harness.store("invoice.paid", client_id, occurred_at=T0 + timedelta(hours=1))

    await harness.process(first)
    await harness.process(second)

    stage, at, _ = await _stage(harness)
    assert (stage, at) == ("paid", T0 + timedelta(hours=1))


async def test_events_of_the_same_instant_apply_in_arrival_order(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    first = await harness.store("quote.sent", client_id, occurred_at=T0)
    second = await harness.store("invoice.paid", client_id, occurred_at=T0)

    await harness.process(first)
    await harness.process(second)

    assert (await _stage(harness))[0] == "paid"


async def test_a_late_deal_won_still_closes_the_deal_and_leaves_the_stage_alone(
    harness: Harness,
) -> None:
    """Q-FIX30-1: `deal.won` уходит при подписании договора, а счёт мог прийти раньше.

    Итог не теряется: сделка закрывается, `closed_at` — по времени события, а `external_stage` и
    название остаются свежими."""
    client_id, _ = await harness.seed_client()
    newer = await harness.store(
        "invoice.paid", client_id, occurred_at=T0 + timedelta(hours=3), title="Новое название"
    )
    late_won = await harness.store("deal.won", client_id, occurred_at=T0, title="Старое название")

    await harness.process(newer)
    await harness.process(late_won)

    (deal,) = await harness.deals()
    assert (deal.stage, deal.closed_at) == ("won", T0)
    assert (deal.external_stage, deal.external_stage_at) == ("paid", T0 + timedelta(hours=3))
    assert deal.title == "Новое название"
    assert deal.amount is not None


async def test_a_late_deal_lost_closes_the_deal_with_its_reason(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    newer = await harness.store("quote.sent", client_id, occurred_at=T0 + timedelta(hours=1))
    late_lost = await harness.store(
        "deal.lost",
        client_id,
        occurred_at=T0,
        stage="lost",
        payload={"amount": "100.00", "currency": "UZS", "lost_reason": "Дорого"},
    )

    await harness.process(newer)
    await harness.process(late_lost)

    (deal,) = await harness.deals()
    assert (deal.stage, deal.lost_reason, deal.external_stage) == ("lost", "Дорого", "quote_sent")


async def test_an_older_outcome_does_not_overturn_a_newer_one(harness: Harness) -> None:
    """Итоги упорядочены между собой: `won` в T0 после `lost` в T0+1ч сделку не переоткрывает."""
    client_id, _ = await harness.seed_client()
    lost = await harness.store(
        "deal.lost",
        client_id,
        occurred_at=T0 + timedelta(hours=1),
        stage="lost",
        payload={"amount": "100.00", "currency": "UZS", "lost_reason": "Дорого"},
    )
    old_won = await harness.store("deal.won", client_id, occurred_at=T0)

    await harness.process(lost)
    await harness.process(old_won)

    (deal,) = await harness.deals()
    assert (deal.stage, deal.closed_at) == ("lost", T0 + timedelta(hours=1))


@pytest.mark.parametrize("event", ["delivery.eta_changed", "delivery.status_changed"])
async def test_a_stale_state_event_reaches_the_feed_but_not_the_client(
    harness: Harness, event: str
) -> None:
    """Устаревший «срок сдвинулся» в бот не идёт (клиент увидит неактуальное), в ленту — да."""
    client_id, _ = await harness.seed_client()
    newer = await harness.store("invoice.paid", client_id, occurred_at=T0 + timedelta(hours=2))
    stale = await harness.store(event, client_id, occurred_at=T0)
    await harness.process(newer)
    harness.bot.sent.clear()

    await harness.process(stale)

    assert harness.bot.sent == []
    assert await harness.notice(stale) is None
    async with harness.sessions() as session:
        notes = (await session.scalars(select(LeadNote.text).order_by(LeadNote.id))).all()
    assert len(notes) == 2, "в ленте есть обе записи"


async def test_a_stale_one_off_fact_still_reaches_the_client(harness: Harness) -> None:
    """КП и счёт — разовые факты: опоздавшее «КП готово» клиенту всё равно нужно."""
    client_id, _ = await harness.seed_client()
    newer = await harness.store("invoice.paid", client_id, occurred_at=T0 + timedelta(hours=2))
    late_quote = await harness.store("quote.sent", client_id, occurred_at=T0)
    await harness.process(newer)
    harness.bot.sent.clear()

    await harness.process(late_quote)

    assert len(harness.bot.sent) == 1


async def test_without_a_bot_the_messages_are_kept_for_the_sweeper(harness: Harness) -> None:
    """Бота нет: `notified_at` не ставится, сообщение не теряется — его досылает сборщик."""
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)
    harness.bot_available = False

    assert await harness.process(event_id) == "processed"
    assert harness.bot.sent == []
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.items
    assert notice.notified_at is None

    harness.bot_available = True
    await _age_notice(harness, event_id, minutes=5)
    assert await harness.notices.sweep() == 1
    assert len(harness.bot.sent) == 1
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.notified_at is not None


async def test_dry_run_does_not_claim_the_messages_either(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    stand = Harness(sessions, telegram_dry_run=True)
    try:
        client_id, _ = await stand.seed_client()
        event_id = await stand.store("quote.sent", client_id)

        assert await stand.process(event_id) == "processed"

        assert stand.bot.sent == []
        notice = await stand.notice(event_id)
        assert notice is not None
        assert notice.notified_at is None
    finally:
        stand.close()


async def test_messages_older_than_a_day_are_closed_without_sending(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    event_id = await harness.store("quote.sent", client_id)
    harness.bot_available = False
    await harness.process(event_id)
    harness.bot_available = True
    await _age_notice(harness, event_id, hours=30)

    assert await harness.notices.sweep() == 0
    assert harness.bot.sent == []
    notice = await harness.notice(event_id)
    assert notice is not None
    assert notice.notified_at is not None, "устаревшее сообщение закрыто, а не висит вечно"


async def test_the_stand_events_pass_the_generated_models(harness: Harness) -> None:
    """Страховка тестового помощника: его события обязаны проходить настоящие модели контракта."""
    for event in STAGES:
        stub = new_event(
            type=event_type_of(event),
            data=data_for(event, 1),
            source="rt://erp",
            time=T0,
        )
        assert isinstance(stub, Event)
        assert parse_erp_event(stub).event == event


async def test_request_created_links_the_mirror_to_the_crm_request_by_its_id(
    harness: Harness,
) -> None:
    """«Создать заявку» (W16-D1-2): `request.created.crm_request_id` связывает событие именно с
    заявкой CRM, даже если у лида есть другая открытая сделка; номер ЗВ из ERP — в `erp_number`."""
    client_id, lead_id = await harness.seed_client()
    async with harness.sessions() as session, session.begin():
        other = Deal(client_id=client_id, lead_id=lead_id, title="Другая открытая", stage="open")
        request = Deal(
            client_id=client_id,
            lead_id=lead_id,
            title="Заявка",
            stage="open",
            request_summary="Нужны оси",
            erp_request_status="pending",
        )
        session.add_all([other, request])
        await session.flush()
        other_id, request_id = other.id, request.id
    data = data_for(
        "request.created",
        client_id,
        payload={"source": "crm", "erp_request_id": ERP_DEAL, "crm_request_id": request_id},
    )
    data["deal"]["number"] = "ЗВ-2026-104"
    event_id = await harness.receive(event_type_of("request.created"), data, time=T0)

    assert await harness.process(event_id) == "processed"

    deals = {deal.id: deal for deal in await harness.deals()}
    assert set(deals) == {other_id, request_id}, "второго зеркала нет"
    assert deals[request_id].erp_deal_id == ERP_DEAL
    assert deals[request_id].erp_number == "ЗВ-2026-104"
    assert deals[other_id].erp_deal_id is None


async def test_crm_request_of_another_client_is_not_adopted(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    other_client, _ = await harness.seed_client(tg_user_id=778)
    async with harness.sessions() as session, session.begin():
        foreign = Deal(client_id=other_client, title="Чужая", stage="open", request_summary="x")
        session.add(foreign)
        await session.flush()
        foreign_id = foreign.id
    data = data_for(
        "request.created",
        client_id,
        payload={"source": "crm", "erp_request_id": ERP_DEAL, "crm_request_id": foreign_id},
    )
    event_id = await harness.receive(event_type_of("request.created"), data, time=T0)

    assert await harness.process(event_id) == "processed"

    deals = {deal.id: deal for deal in await harness.deals()}
    assert deals[foreign_id].erp_deal_id is None
    assert [d.client_id for d in deals.values() if d.erp_deal_id == ERP_DEAL] == [client_id]
