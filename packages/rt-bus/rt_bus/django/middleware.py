"""Middleware Django: корреляция запроса (`X-Request-ID`, `traceparent`) в контекст rt_bus.

`MIDDLEWARE = ["rt_bus.django.middleware.CorrelationMiddleware", ...]` — тогда `publish` в обработке запроса берёт
`correlationid` из `X-Request-ID` (иначе новый UUID), а ответ получает заголовок `X-Request-ID`. Если у сервиса уже есть
свой middleware request-id, достаточно вызвать в нём `rt_bus.context.set_correlation(...)`.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponseBase

from ..context import REQUEST_ID_HEADER, correlation, correlation_from_headers


class CorrelationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        cid, traceparent = correlation_from_headers(dict(request.headers))
        with correlation(cid, traceparent):
            response = self.get_response(request)
        if REQUEST_ID_HEADER not in response:
            response[REQUEST_ID_HEADER] = cid
        return response
