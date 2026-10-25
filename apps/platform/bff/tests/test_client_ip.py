"""Адрес клиента за Caddy: X-Forwarded-For только от доверенного прокси, журнал, передача в CRM."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.client_ip import DEFAULT_TRUSTED_PROXIES, parse_networks, resolve_client_ip
from tests.conftest import Web

NETS = parse_networks(DEFAULT_TRUSTED_PROXIES)


def _journal(capsys: pytest.CaptureFixture[str], event: str) -> list[dict[str, object]]:
    """Записи журнала BFF (JSON в stdout) с нужным событием."""
    records = []
    for line in capsys.readouterr().out.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == event:
            records.append(record)
    return records


@pytest.mark.parametrize(
    ("forwarded", "peer", "expected"),
    [
        # Caddy во внутренней сети ставит один адрес — адрес клиента.
        ("203.0.113.5", "172.18.0.5", "203.0.113.5"),
        # Заголовок от клиента не подменяет адрес: Caddy дописывает свой адрес справа.
        ("1.1.1.1, 203.0.113.5", "172.18.0.5", "203.0.113.5"),
        # Цепочка доверенных прокси: пропускаем свои, берём первый чужой справа.
        ("203.0.113.5, 10.1.2.3", "172.18.0.5", "203.0.113.5"),
        # Партнёр не доверенный (в обход Caddy): заголовок игнорируется.
        ("1.1.1.1", "198.51.100.77", "198.51.100.77"),
        # Нет заголовка, пустой заголовок: адрес сокета.
        (None, "172.18.0.5", "172.18.0.5"),
        ("  ", "172.18.0.5", "172.18.0.5"),
        # Нечитаемый элемент цепочки в ключ лимита не попадает.
        ("not-an-ip", "172.18.0.5", "172.18.0.5"),
        ("203.0.113.5, junk", "172.18.0.5", "172.18.0.5"),
        # IPv6 и IPv4-in-IPv6.
        ("2001:db8::7", "172.18.0.5", "2001:db8::7"),
        ("::ffff:203.0.113.6", "172.18.0.5", "203.0.113.6"),
        # Сокета нет или он нечитаем.
        ("1.1.1.1", None, "unknown"),
        ("1.1.1.1", "testclient", "unknown"),
    ],
)
def test_resolve_client_ip(forwarded: str | None, peer: str | None, expected: str) -> None:
    assert resolve_client_ip(forwarded, peer, NETS) == expected


def test_empty_trusted_list_ignores_the_header() -> None:
    assert resolve_client_ip("203.0.113.5", "172.18.0.5", parse_networks("")) == "172.18.0.5"


def test_single_address_is_a_network() -> None:
    nets = parse_networks("192.0.2.7, 2001:db8::/32")
    assert resolve_client_ip("203.0.113.5", "192.0.2.7", nets) == "203.0.113.5"
    assert resolve_client_ip("203.0.113.5", "192.0.2.8", nets) == "192.0.2.8"
    assert resolve_client_ip("203.0.113.5", "2001:db8::1", nets) == "203.0.113.5"


@pytest.fixture
async def outside(web: Web) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент, достучавшийся до BFF в обход Caddy: сокет с публичным адресом."""
    transport = httpx.ASGITransport(app=web.app, client=("198.51.100.77", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="https://bff.test") as http:
        yield http


async def test_untrusted_header_does_not_replace_the_ip_in_the_limiter(
    web: Web, outside: httpx.AsyncClient
) -> None:
    """Подделка X-Forwarded-For не даёт обойти лимит и не даёт заблокировать чужой адрес."""
    statuses = []
    for i in range(12):
        response = await outside.post(
            "/api/v1/auth/login",
            json={"email": f"user{i}@example.org", "password": "nope"},
            headers={"X-Forwarded-For": f"192.0.2.{i}"},
        )
        statuses.append(response.status_code)

    assert statuses == [401] * 10 + [429] * 2
    assert "rl:login:ip:198.51.100.77" in web.redis.values
    assert not [k for k in web.redis.values if k.startswith("rl:login:ip:192.0.2.")]


async def test_trusted_proxy_forwarded_ip_is_used_for_limit_and_crm(web: Web) -> None:
    response = await web.login(ip="203.0.113.5")

    assert response.status_code == 200
    assert web.be.crm_login.calls.last.request.headers["x-forwarded-for"] == "203.0.113.5"


async def test_forwarded_ip_is_in_the_failed_login_journal(
    web: Web, capsys: pytest.CaptureFixture[str]
) -> None:
    await web.login(password="nope", ip="203.0.113.5")

    failed = _journal(capsys, "login_failed")
    assert len(failed) == 1
    assert failed[0]["client_ip"] == "203.0.113.5"
    assert failed[0]["code"] == "INVALID_CREDENTIALS"
    assert "request_id" in failed[0]
    assert "ivan.test" not in str(failed[0])  # e-mail в журнал не пишется, только короткий хеш


async def test_untrusted_header_does_not_replace_the_ip_in_the_journal(
    outside: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await outside.post(
        "/api/v1/auth/login",
        json={"email": "ivan.test@example.org", "password": "nope"},
        headers={"X-Forwarded-For": "192.0.2.1"},
    )

    failed = _journal(capsys, "login_failed")
    assert failed[0]["client_ip"] == "198.51.100.77"


async def test_rate_limited_attempt_is_journaled(
    web: Web, capsys: pytest.CaptureFixture[str]
) -> None:
    for _ in range(10):
        await web.login(password="nope", ip="203.0.113.5")
    capsys.readouterr()

    await web.login(password="nope", ip="203.0.113.5")

    limited = _journal(capsys, "login_rate_limited")
    assert len(limited) == 1
    assert limited[0]["client_ip"] == "203.0.113.5"
