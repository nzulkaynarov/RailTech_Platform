"""Адрес клиента за доверенным прокси — одна функция на журналы портала (FX-4, решение архитектора: IP одним местом).

Берём то же, что лимиты запросов DRF (`SimpleRateThrottle.get_ident`, настройка `NUM_PROXIES`, SEC-04): на проде перед ERP один
прокси — Caddy, он заменяет присланный клиентом `X-Forwarded-For` настоящим адресом (trusted_proxies не заданы), в dev `NUM_PROXIES=0`
и заголовок игнорируется. Правее последнего доверенного прокси клиент дописать не может, поэтому подделка не попадает в журнал
и не обходит лимит. Значение, не являющееся IP-адресом (запрос в обход прокси), отбрасывается: поле журнала — `inet`.
"""

from __future__ import annotations

import ipaddress

from rest_framework.throttling import BaseThrottle


def client_ip(request) -> str:
    candidate = BaseThrottle().get_ident(request) or ""
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return request.META.get("REMOTE_ADDR") or ""
    return candidate
