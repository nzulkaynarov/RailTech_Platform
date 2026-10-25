"""Адрес клиента за Caddy: `X-Forwarded-For` берётся только от доверенного прокси.

Caddy (`reverse_proxy`) сам дописывает в `X-Forwarded-For` адрес, с которого пришёл запрос, и не
верит такому заголовку от посторонних (в Caddyfile `trusted_proxies` не задан). BFF стоит за Caddy
во внутренней сети compose и наружу не публикуется, но заголовку верит не слепо: идёт справа налево
по цепочке, пока очередной адрес входит в доверенные сети; первый адрес вне доверенных и есть
клиент. Если сокет-партнёр сам не доверенный (достучались до BFF в обход Caddy), заголовок
игнорируется целиком.
"""

import ipaddress
from collections.abc import Sequence

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

# Сети, которым по умолчанию верит BFF: loopback и частные диапазоны (сеть compose, Docker Desktop).
DEFAULT_TRUSTED_PROXIES = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
UNKNOWN = "unknown"

type Network = ipaddress.IPv4Network | ipaddress.IPv6Network
type Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def parse_networks(raw: str) -> tuple[Network, ...]:
    """`10.0.0.0/8, 192.0.2.7` -> сети (адрес — сеть из одного адреса); ошибка — ValueError."""
    return tuple(
        ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip()
    )


def _address(raw: str) -> Address | None:
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _trusted(ip: Address, networks: Sequence[Network]) -> bool:
    return any(ip.version == net.version and ip in net for net in networks)


def resolve_client_ip(
    forwarded_for: str | None, peer: str | None, networks: Sequence[Network]
) -> str:
    """Адрес клиента: сокет-партнёр, а за доверенными прокси — адрес из `X-Forwarded-For`.

    Нет разборчивого адреса сокета — `unknown`. Нечитаемый элемент цепочки не принимается на веру:
    берётся последний прочитанный адрес (произвольную строку в ключ лимита подсунуть нельзя).
    """
    candidate = _address(peer) if peer else None
    if candidate is None:
        return UNKNOWN
    if forwarded_for:
        for raw in reversed(forwarded_for.split(",")):
            if not _trusted(candidate, networks):
                break
            hop = _address(raw)
            if hop is None:
                break
            candidate = hop
    return str(candidate)


class ClientIpMiddleware:
    """Определяет адрес клиента (`request.state.client_ip`) и кладёт его в каждую запись журнала."""

    def __init__(self, app: ASGIApp, networks: Sequence[Network]) -> None:
        self.app = app
        self.networks = tuple(networks)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        chain = ",".join(headers.getlist("x-forwarded-for")) or None
        client = scope.get("client")
        ip = resolve_client_ip(chain, client[0] if client else None, self.networks)
        scope.setdefault("state", {})["client_ip"] = ip
        structlog.contextvars.bind_contextvars(client_ip=ip)
        try:
            await self.app(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars("client_ip")
