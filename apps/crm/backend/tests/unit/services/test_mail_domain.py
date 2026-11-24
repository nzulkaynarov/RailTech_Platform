"""E-mail domain check at lead intake: clear «no mail here» blocks, DNS trouble does not."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import dns.exception
import dns.resolver
import pytest

from app.domain.errors import ValidationFailedError
from app.domain.web_form import issue_form_token
from app.schemas.lead_intake import WebLeadIn
from app.schemas.settings import AppSettings
from app.services.lead_intake import LeadIntakeService
from app.services.mail_domain import DnsMailDomainChecker, DomainVerdict

KEY = b"unit-form-key"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


class _Mx:
    def __init__(self, host: str) -> None:
        self.exchange = host


class FakeResolver:
    """`behaviour(name, kind)` returns answers or raises the dnspython exception."""

    def __init__(self, behaviour: Callable[[str, str], list[Any]]) -> None:
        self.behaviour = behaviour
        self.calls: list[tuple[str, str]] = []
        self.timeout = 0.0
        self.lifetime = 0.0

    async def resolve(self, name: str, kind: str) -> list[Any]:
        self.calls.append((name, kind))
        return self.behaviour(name, kind)


def checker(
    behaviour: Callable[[str, str], list[Any]],
) -> tuple[DnsMailDomainChecker, FakeResolver]:
    resolver = FakeResolver(behaviour)
    return DnsMailDomainChecker(cast(Any, resolver)), resolver


def nxdomain(_: str, __: str) -> list[Any]:
    raise dns.resolver.NXDOMAIN()  # type: ignore[no-untyped-call]


def no_answer(_: str, __: str) -> list[Any]:
    raise dns.resolver.NoAnswer()  # type: ignore[no-untyped-call]


def timeout(_: str, __: str) -> list[Any]:
    raise dns.exception.Timeout()  # type: ignore[no-untyped-call]


async def test_nxdomain_is_missing() -> None:
    svc, _ = checker(nxdomain)
    assert await svc.check("tvorog.io") is DomainVerdict.MISSING


async def test_mx_present_is_ok() -> None:
    svc, _ = checker(lambda n, k: [_Mx("mx.yandex.net.")])
    assert await svc.check("yandex.ru") is DomainVerdict.OK


async def test_null_mx_is_missing() -> None:
    svc, _ = checker(lambda n, k: [_Mx(".")])
    assert await svc.check("nomail.example") is DomainVerdict.MISSING


async def test_no_mx_falls_back_to_address() -> None:
    def behaviour(name: str, kind: str) -> list[Any]:
        if kind == "MX":
            raise dns.resolver.NoAnswer()  # type: ignore[no-untyped-call]
        if kind == "A":
            raise dns.resolver.NoAnswer()  # type: ignore[no-untyped-call]
        return ["2001:db8::1"]  # AAAA only

    svc, resolver = checker(behaviour)
    assert await svc.check("v6only.example") is DomainVerdict.OK
    assert [k for _, k in resolver.calls] == ["MX", "A", "AAAA"]


async def test_no_mx_and_no_address_is_missing() -> None:
    svc, _ = checker(no_answer)
    assert await svc.check("empty.example") is DomainVerdict.MISSING


async def test_dns_timeout_is_unknown_not_missing() -> None:
    svc, _ = checker(timeout)
    assert await svc.check("slow.example") is DomainVerdict.UNKNOWN


async def test_dns_failure_on_address_fallback_is_unknown() -> None:
    def behaviour(name: str, kind: str) -> list[Any]:
        if kind == "MX":
            raise dns.resolver.NoAnswer()  # type: ignore[no-untyped-call]
        raise dns.resolver.NoNameservers()  # type: ignore[no-untyped-call]

    svc, _ = checker(behaviour)
    assert await svc.check("broken.example") is DomainVerdict.UNKNOWN


async def test_verdict_is_cached_per_domain_and_unknown_is_not() -> None:
    svc, resolver = checker(lambda n, k: [_Mx("mx.example.")])
    await svc.check("Cached.Example")
    await svc.check("cached.example.")
    assert len(resolver.calls) == 1
    slow, slow_resolver = checker(timeout)
    await slow.check("slow.example")
    await slow.check("slow.example")
    assert len(slow_resolver.calls) == 2


class _Settings:
    async def get(self) -> AppSettings:
        return AppSettings()


class _NoDb:
    def __call__(self) -> Any:
        raise AssertionError("database reached")


class _Verdict:
    def __init__(self, verdict: DomainVerdict) -> None:
        self.verdict = verdict
        self.asked: list[str] = []

    async def check(self, domain: str) -> DomainVerdict:
        self.asked.append(domain)
        return self.verdict


def intake(verdict: DomainVerdict) -> tuple[LeadIntakeService, _Verdict]:
    fake = _Verdict(verdict)
    service = LeadIntakeService(
        cast(Any, _NoDb()), cast(Any, _Settings()), KEY, mail_domains=cast(Any, fake)
    )
    return service, fake


def web_body(**patch: Any) -> WebLeadIn:
    base: dict[str, Any] = {
        "name": "Алишер",
        "phone": None,
        "email": "em@tvorog.io",
        "text": "Нужна интеграция",
        "form_token": issue_form_token(KEY, NOW - timedelta(seconds=30)),
        "consent": True,
    }
    return WebLeadIn(**{**base, **patch})


async def test_web_lead_with_missing_domain_is_422_invalid_email() -> None:
    service, fake = intake(DomainVerdict.MISSING)
    with pytest.raises(ValidationFailedError) as info:
        await service.create_web(web_body(), "1.1.1.1", NOW)
    assert info.value.details["reason"] == "invalid_email"
    assert info.value.details["field"] == "email"
    assert fake.asked == ["tvorog.io"]


@pytest.mark.parametrize("verdict", [DomainVerdict.OK, DomainVerdict.UNKNOWN])
async def test_ok_and_dns_trouble_do_not_block(verdict: DomainVerdict) -> None:
    service, _ = intake(verdict)
    # Past the domain check the request goes on to the database (forbidden here).
    with pytest.raises(AssertionError, match="database reached"):
        await service.create_web(web_body(), "1.1.1.1", NOW)


async def test_phone_only_lead_is_not_checked() -> None:
    service, fake = intake(DomainVerdict.MISSING)
    with pytest.raises(AssertionError, match="database reached"):
        await service.create_web(web_body(email=None, phone="+998901234567"), "1.1.1.1", NOW)
    assert fake.asked == []


async def test_manual_lead_with_missing_domain_is_422_too() -> None:
    from app.schemas.lead_intake import ManualLeadIn

    service, _ = intake(DomainVerdict.MISSING)
    body = ManualLeadIn(name="Иван", source="email", email="a@nowhere.invalid")
    with pytest.raises(ValidationFailedError) as info:
        await service.create_manual(cast(Any, object()), body)
    assert info.value.details["field"] == "email"


async def test_one_overall_budget_for_all_queries() -> None:
    """MX, A and AAAA share one 2 s budget: slow DNS is `unknown` after ~2 s, not after 3 x 2 s."""
    import asyncio
    import time

    class Slow:
        timeout = 0.0
        lifetime = 0.0

        async def resolve(self, name: str, kind: str) -> list[Any]:
            await asyncio.sleep(1.5)
            raise dns.resolver.NoAnswer()  # type: ignore[no-untyped-call]

    started = time.monotonic()
    verdict = await DnsMailDomainChecker(cast(Any, Slow())).check("slow.example")
    assert verdict is DomainVerdict.UNKNOWN
    assert time.monotonic() - started < 2.6
