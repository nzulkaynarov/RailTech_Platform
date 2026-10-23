"""HTTP-клиент доставки шины rt_bus в ERP: ответ подписчика проходит маску секретов (FIX-66b, B3).

Библиотека пишет в `rt_bus_delivery.last_error` начало тела ответа подписчика (до усечения). Чужой сервис бывает
эхом возвращает заголовки запроса (`Authorization: Bearer …`, ключи) — как раньше с ответом CRM на вебхук. Маска
`core.log_mask.mask_secrets` применяется к ТЕЛУ ответа ещё в транспорте, до усечения библиотекой: секрет на границе
обрезки не теряет хвост и не оседает в журнале DLQ, админке и бэкапах.
"""

from __future__ import annotations

from typing import Optional

import httpx

from core.log_mask import mask_secrets

#: Заголовки, описывающие исходное тело: после подмены тела они были бы ложью.
_BODY_HEADERS = {"content-length", "content-encoding", "transfer-encoding"}


class SecretMaskingTransport(httpx.BaseTransport):
    """Обёртка над транспортом httpx: тело ответа возвращается с замаскированными секретами."""

    def __init__(self, inner: Optional[httpx.BaseTransport] = None) -> None:
        self._inner = inner if inner is not None else httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        try:
            response.read()
            body = mask_secrets(response.text).encode("utf-8")
            headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _BODY_HEADERS]
            return httpx.Response(response.status_code, headers=headers, content=body, request=request)
        finally:
            response.close()

    def close(self) -> None:
        self._inner.close()


def build_http_client(timeout: float, inner: Optional[httpx.BaseTransport] = None) -> httpx.Client:
    """Клиент доставки шины: без редиректов (как в библиотеке), ответы — через маску секретов."""
    return httpx.Client(timeout=timeout, follow_redirects=False, transport=SecretMaskingTransport(inner))
