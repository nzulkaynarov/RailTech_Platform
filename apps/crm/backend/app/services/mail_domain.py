"""Can the e-mail domain receive mail at all (checked when a lead is accepted)?

DNS MX, falling back to A/AAAA (RFC 5321 §5.1: no MX — the domain itself is the mail host). A short
timeout and a per-domain cache keep the form fast. Only a clear «no such domain / no mail host»
(NXDOMAIN, or no MX and no address, or the null MX of RFC 7505) is `MISSING` and blocks the
request; any DNS trouble (timeout, SERVFAIL, no resolver) is `UNKNOWN` and never blocks (fail-open):
the form must not lose a real lead because of our resolver.
"""

import asyncio
import time
from enum import StrEnum
from typing import Protocol

import dns.asyncresolver
import dns.exception
import dns.name
import dns.resolver
import structlog

logger = structlog.get_logger(__name__)

TIMEOUT_S = 2.0
OK_TTL_S = 3600.0
MISSING_TTL_S = 600.0
CACHE_MAX = 2048


class DomainVerdict(StrEnum):
    OK = "ok"
    MISSING = "missing"
    UNKNOWN = "unknown"


class MailDomainChecker(Protocol):
    async def check(self, domain: str) -> DomainVerdict: ...


class DnsMailDomainChecker:
    """Production checker over `dnspython`; `resolver` is replaceable in tests."""

    def __init__(self, resolver: dns.asyncresolver.Resolver | None = None) -> None:
        self._resolver = resolver or dns.asyncresolver.Resolver()
        self._resolver.timeout = TIMEOUT_S
        self._resolver.lifetime = TIMEOUT_S
        self._cache: dict[str, tuple[DomainVerdict, float]] = {}

    async def check(self, domain: str) -> DomainVerdict:
        name = domain.strip().strip(".").lower()
        cached = self._cache.get(name)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        try:
            verdict = await asyncio.wait_for(self._lookup(name), TIMEOUT_S + 1)
        except Exception as exc:  # noqa: BLE001 — any DNS trouble must not block the form
            logger.warning("mail_domain_dns_unavailable", error=type(exc).__name__)
            return DomainVerdict.UNKNOWN
        ttl = OK_TTL_S if verdict is DomainVerdict.OK else MISSING_TTL_S
        if len(self._cache) >= CACHE_MAX:
            self._cache.clear()
        self._cache[name] = (verdict, time.monotonic() + ttl)
        return verdict

    async def _lookup(self, name: str) -> DomainVerdict:
        try:
            answer = await self._resolver.resolve(name, "MX")
        except dns.resolver.NXDOMAIN:
            return DomainVerdict.MISSING
        except dns.resolver.NoAnswer:
            return await self._address(name)
        hosts = [str(r.exchange).strip(".") for r in answer]
        # Null MX (RFC 7505): the domain states that it takes no mail.
        return DomainVerdict.MISSING if not any(hosts) else DomainVerdict.OK

    async def _address(self, name: str) -> DomainVerdict:
        for kind in ("A", "AAAA"):
            try:
                await self._resolver.resolve(name, kind)
            except dns.resolver.NXDOMAIN:
                return DomainVerdict.MISSING
            except dns.resolver.NoAnswer:
                continue
            return DomainVerdict.OK
        return DomainVerdict.MISSING
