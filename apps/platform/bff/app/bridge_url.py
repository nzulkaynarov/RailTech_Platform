"""Публичные адреса старых фронтов (мост W15-H1): проверка настройки и вывод из адреса Платформы.

Без правки `.env` на типовой установке: Платформа открыта на `platform.<домен>[:порт]`, старые
фронты — на `crm.<домен>` и `erp.<домен>` с тем же портом (`infra/caddy`, `.env.prod.example`).
Хост берётся из заголовка `Host` (Caddy его не меняет), схема — из `X-Forwarded-Proto`, но только
от доверенного прокси. Хост проверяется по строгому шаблону: в адрес для кнопки попадает только
`схема://метка.метка[:порт]`.
"""

import re
from collections.abc import Sequence
from urllib.parse import urlsplit

from app.client_ip import Network, is_trusted_peer

PLATFORM_LABEL = "platform"

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"^({_LABEL}(?:\.{_LABEL})*)(?::(\d{{1,5}}))?$")


def valid_public_url(url: str) -> bool:
    """`http(s)://хост[:порт]` без пути, запроса и учётных данных."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username:
        return False
    try:
        parts.port  # noqa: B018 — разбор порта бросает ValueError на мусоре
    except ValueError:
        return False
    return True


def derive_public_url(
    host_header: str | None,
    forwarded_proto: str | None,
    peer: str | None,
    networks: Sequence[Network],
    *,
    sibling: str,
    request_scheme: str,
) -> str | None:
    """`platform.X[:порт]` -> `<схема>://<sibling>.X[:порт]`; хост не в этом виде — `None`."""
    if not host_header:
        return None
    match = _HOST.match(host_header.strip().lower())
    if match is None:
        return None
    labels = match.group(1).split(".")
    port = match.group(2)
    if len(labels) < 2 or labels[0] != PLATFORM_LABEL:
        return None
    if port is not None and not 0 < int(port) < 65536:
        return None
    scheme = request_scheme
    if forwarded_proto and is_trusted_peer(peer, networks):
        proto = forwarded_proto.split(",")[0].strip().lower()
        if proto in {"http", "https"}:
            scheme = proto
    host = ".".join([sibling, *labels[1:]])
    return f"{scheme}://{host}" + (f":{port}" if port else "")
