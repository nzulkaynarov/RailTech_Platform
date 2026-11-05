"""«Проверить почту» (MAIL-NOW) на Postgres и фейковом IMAP: опрос сразу, общая блокировка с
плановой задачей, частота не чаще раза в 20 секунд, итог без деталей сервера. Адреса вымышленные."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import RateLimitedError
from app.integrations.imap import FetchBatch, ImapConnection
from app.main import create_app
from app.security.secrets_store import IMAP_PASSWORD
from app.services.inbound_mail_check import InboundMailCheck
from app.services.inbound_mail_ingest import InboundMailIngest, PollBusy, PollOutcome, PollTooSoon
from tests.fake_imap import FakeImapServer, PlainClient
from tests.integration.test_inbound_mail import BUCKET, SECRETS_KEY, Stand, _raw, _staff

pytestmark = pytest.mark.integration


@pytest.fixture
def server() -> Iterator[FakeImapServer]:
    with FakeImapServer() as running:
        yield running


@pytest.fixture
def stand(sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> Stand:
    return Stand(sessions, server)


@pytest.fixture
def api(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, server: FakeImapServer
) -> Iterator[tuple[TestClient, Stand]]:
    app = create_app(live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)}))
    with TestClient(app) as http:
        stand = Stand(sessions, server, app.state.container.settings_service)
        app.state.container.__dict__["inbound_mail_check"] = InboundMailCheck(stand.ingest)
        yield http, stand


class GatedClient(PlainClient):
    """Настоящий клиент, но чтение ящика ждёт сигнала: тест держит опрос «в процессе»."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(
        self, connection: ImapConnection, uidvalidity: int | None, last_uid: int | None
    ) -> FetchBatch:
        self.entered.set()
        await self.release.wait()
        return await super().fetch(connection, uidvalidity, last_uid)


def _check(stand: Stand, **kw: object) -> InboundMailCheck:
    return InboundMailCheck(stand.ingest, **kw)  # type: ignore[arg-type]


def _gated(stand: Stand) -> GatedClient:
    gated = GatedClient()
    stand.ingest = InboundMailIngest(
        stand.sessions, stand.store, stand.settings, gated, stand.storage, BUCKET
    )
    return gated


async def test_check_pulls_new_mail_immediately(stand: Stand) -> None:
    await stand.configure()
    stand.server.box.add(7, _raw(1))
    out = await _check(stand).check()
    assert (out.status, out.created, out.error_kind) == ("ok", 1, None)
    assert out.checked_at is not None
    assert len(await stand.mails()) == 1


async def test_check_without_settings_is_off_and_does_not_touch_the_server(stand: Stand) -> None:
    out = await _check(stand).check()
    assert (out.status, out.created) == ("off", 0)
    assert stand.server.box.logins == 0


async def test_second_check_within_20_seconds_is_rate_limited_and_skips_the_server(
    stand: Stand,
) -> None:
    await stand.configure()
    stand.server.box.add(7, _raw(1))
    check = _check(stand)
    await check.check()
    logins = stand.server.box.logins
    with pytest.raises(RateLimitedError) as caught:
        await check.check()
    assert 1 <= (caught.value.retry_after_s or 0) <= 20
    assert stand.server.box.logins == logins, "сервер второй раз не опрашивали"
    # после паузы — снова можно
    assert isinstance(await stand.ingest.poll_exclusive(timedelta(0)), PollOutcome)


async def test_two_checks_at_once_read_the_mailbox_once(stand: Stand) -> None:
    """Двойной клик (или два делопроизводителя): второй видит «уже проверяется», второго опроса нет.
    Мутационная проверка — в PR: без `pg_try_advisory_xact_lock` оба читают ящик."""
    await stand.configure()
    stand.server.box.add(7, _raw(1))
    gated = _gated(stand)
    check = _check(stand, wait_s=3)
    first = asyncio.create_task(check.check())
    await asyncio.wait_for(gated.entered.wait(), 10)
    second = await check.check()
    assert (second.status, second.created) == ("checking", 0)
    gated.release.set()
    done = await first
    assert (done.status, done.created) == ("ok", 1)
    assert stand.server.box.logins == 1
    assert len(await stand.mails()) == 1


async def test_scheduled_poll_skips_while_a_manual_check_runs(stand: Stand) -> None:
    await stand.configure()
    stand.server.box.add(7, _raw(1))
    gated = _gated(stand)
    running = asyncio.create_task(_check(stand).check())
    await asyncio.wait_for(gated.entered.wait(), 10)
    assert isinstance(await asyncio.wait_for(stand.ingest.poll_exclusive(), 3), PollBusy)
    gated.release.set()
    assert (await running).status == "ok"
    assert isinstance(await stand.ingest.poll_exclusive(), PollOutcome)


async def test_slow_poll_answers_checking_and_finishes_in_background(stand: Stand) -> None:
    await stand.configure()
    stand.server.box.add(7, _raw(1))
    gated = _gated(stand)
    check = _check(stand, wait_s=0.05)
    out = await check.check()
    assert (out.status, out.checked_at) == ("checking", None)
    assert await stand.mails() == []
    gated.release.set()
    await asyncio.wait_for(asyncio.gather(*check._background), 10)
    assert len(await stand.mails()) == 1, "опрос доехал в фоне"


async def test_error_reports_only_the_kind_not_server_details(stand: Stand) -> None:
    await stand.configure()
    async with stand.sessions() as session, session.begin():
        await stand.store.put(session, IMAP_PASSWORD, "wrong-password-xyz", None)
    out = await _check(stand).check()
    assert (out.status, out.error_kind) == ("error", "auth_failed")
    dumped = out.model_dump_json()
    for leak in ("127.0.0.1", "wrong-password-xyz", "inbox@company.test", "AUTHENTICATIONFAILED"):
        assert leak not in dumped


async def test_unexpected_failure_is_an_error_without_details(stand: Stand) -> None:
    class Broken(InboundMailIngest):
        async def poll_exclusive(self, min_interval=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("db password=hunter2 at 10.0.0.5")

    broken = Broken(
        stand.sessions, stand.store, stand.settings, PlainClient(), stand.storage, BUCKET
    )
    out = await InboundMailCheck(broken).check()
    assert (out.status, out.error_kind) == ("error", "internal")
    assert "hunter2" not in out.model_dump_json()


async def test_too_soon_is_reported_with_seconds(stand: Stand) -> None:
    await stand.configure()
    await stand.ingest.poll()
    result = await stand.ingest.poll_exclusive(timedelta(seconds=20))
    assert isinstance(result, PollTooSoon)
    assert 1 <= result.retry_after_s <= 20


# --- API ---------------------------------------------------------------------------------------


async def test_api_check_returns_outcome_then_429_with_retry_after(
    api: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = api
    clerk = await _staff(http, sessions, "clerk-now@railtech.uz", "tpl:REGISTRAR")

    assert http.post("/api/v1/inbound-mail/poll").status_code == 401

    off = http.post("/api/v1/inbound-mail/poll", headers=clerk)
    assert (off.status_code, off.json()["status"]) == (200, "off")

    await stand.configure()
    stand.server.box.add(7, _raw(1))
    ok = http.post("/api/v1/inbound-mail/poll", headers=clerk)
    assert ok.status_code == 200, ok.text
    assert (ok.json()["status"], ok.json()["created"]) == ("ok", 1)
    assert ok.json()["checked_at"]

    again = http.post("/api/v1/inbound-mail/poll", headers=clerk)
    assert again.status_code == 429
    assert 1 <= int(again.headers["Retry-After"]) <= 20
    assert again.json()["code"] == "rate_limited"
    assert again.json()["details"]["retry_after_s"] == int(again.headers["Retry-After"])
    assert stand.server.box.logins == 1


async def test_api_check_is_open_to_any_employee_like_the_queue(
    api: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, _ = api
    seller = await _staff(http, sessions, "seller-now@railtech.uz", "tpl:MANAGER_ALL")
    assert http.post("/api/v1/inbound-mail/poll", headers=seller).status_code == 200
