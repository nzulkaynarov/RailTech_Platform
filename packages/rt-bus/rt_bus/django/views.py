"""View приёмника Django: `path("bus/v1/events", bus_view(get_bus))`.

`bus` — `DjangoBus` или функция без аргументов, возвращающая его (ленивое создание при первом запросе).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from .bus import DjangoBus


def bus_view(bus: DjangoBus | Callable[[], DjangoBus]) -> Callable[[HttpRequest], HttpResponse]:
    @csrf_exempt
    @require_POST
    def view(request: HttpRequest) -> HttpResponse:
        target = bus() if callable(bus) else bus
        result = target.receive(dict(request.headers), request.body)
        return JsonResponse(result.body, status=result.status_code)

    return view
