"""Защита сессии портала в cookie от CSRF: только JSON и обязательный `Idempotency-Key` (FIX-15, аудит C-12).

Сессия портала лежит в cookie, а для Telegram Mini App она `SameSite=None` — браузер приложит её и к запросу
с чужого сайта. Межсайтовая форма (`<form method=post>`, `fetch` с `no-cors`) умеет слать только «простые»
запросы: `GET`/`POST`, тело `application/x-www-form-urlencoded`, `multipart/form-data` или `text/plain` и никаких
своих заголовков. Поэтому на `/api/portal/*` запрос `POST` и `PATCH` принимается, только если

1. несёт `Idempotency-Key` (CONTRACTS §0) — свой заголовок делает запрос «непростым», браузер сначала шлёт
   preflight, а CORS пускает лишь origin Cabinet;
2. его тело — `application/json` (то же самое по типу содержимого: форма JSON отправить не может).

Исключение по типу — `POST /uploads`: файл не уложить в JSON (Q-14), остаётся `multipart/form-data`;
от межсайтовой формы его защищает пункт 1.

Ошибки: 400 `IDEMPOTENCY_KEY_REQUIRED`, 415 `UNSUPPORTED_MEDIA_TYPE` — формат `{"detail": "<CODE>"}`.
"""

from django.http import JsonResponse

PORTAL_PREFIX = "/api/portal/"
# PUT и DELETE — «непростые» методы: браузер и так шлёт для них preflight, а CORS пускает только origin Cabinet.
# Опасны POST (форма умеет его слать без preflight) и PATCH (по CONTRACTS §0 — как POST).
GUARDED_METHODS = frozenset({"POST", "PATCH"})
UPLOADS_PATHS = frozenset({"/api/portal/v1/uploads", "/api/portal/v1/uploads/"})


class PortalRequestGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(PORTAL_PREFIX) and request.method in GUARDED_METHODS:
            if not (request.headers.get("Idempotency-Key") or "").strip():
                return JsonResponse({"detail": "IDEMPOTENCY_KEY_REQUIRED"}, status=400)
            if not self._media_type_allowed(request):
                return JsonResponse({"detail": "UNSUPPORTED_MEDIA_TYPE"}, status=415)
        return self.get_response(request)

    @staticmethod
    def _media_type_allowed(request) -> bool:
        try:
            has_body = int(request.META.get("CONTENT_LENGTH") or 0) > 0
        except ValueError:
            has_body = True
        if not has_body and not request.META.get("HTTP_TRANSFER_ENCODING"):
            return True  # logout и подобные запросы без тела: слать в них нечего, ключ уже проверен
        media_type = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
        if media_type == "application/json":
            return True
        return media_type == "multipart/form-data" and request.path in UPLOADS_PATHS
