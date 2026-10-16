"""Integration idempotency handling (CONTRACTS §0, §2, M3-ERP-01).

Гарантирует обработку заголовка `Idempotency-Key` (UUIDv4) для мутирующих запросов.
При повторном вызове с тем же ключом и телом — возвращает первый ответ.
При повторном вызове с тем же ключом, но другим телом — 409 IDEMPOTENCY_CONFLICT.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from .exceptions import IntegrationIdempotencyConflict, IntegrationValidationError
from .models import IntegrationIdempotencyKey

logger = logging.getLogger(__name__)


def handle_idempotency(view_method):
    """Декоратор для методов POST view, требующих Idempotency-Key."""

    @wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        key_header = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
        if not key_header:
            raise IntegrationValidationError("VALIDATION_ERROR")

        try:
            key_uuid = uuid.UUID(str(key_header).strip())
        except (ValueError, AttributeError, TypeError):
            raise IntegrationValidationError("VALIDATION_ERROR")

        # Вычисляем SHA-256 хэш тела запроса (нормализуя через request.data или сырой body)
        try:
            if hasattr(request, "data") and request.data:
                body_bytes = json.dumps(request.data, sort_keys=True, default=str).encode("utf-8")
            else:
                body_bytes = request.body or b""
        except Exception:
            body_bytes = request.body or b""
        request_hash = hashlib.sha256(body_bytes).hexdigest()

        # Проверяем существующую запись
        existing = IntegrationIdempotencyKey.objects.filter(key=key_uuid).first()
        if existing:
            if existing.is_expired(ttl_days=7):
                existing.delete()
            elif existing.request_hash == request_hash:
                logger.debug("Idempotent hit for key %s", key_uuid)
                return Response(data=existing.response_body, status=existing.response_status)
            else:
                logger.warning("Idempotency conflict for key %s", key_uuid)
                raise IntegrationIdempotencyConflict("IDEMPOTENCY_CONFLICT")

        response = view_method(self, request, *args, **kwargs)

        # Сохраняем результат для успешных статусов
        if status.is_success(response.status_code) and isinstance(response.data, (dict, list)):
            body_dict = json.loads(json.dumps(response.data))
            IntegrationIdempotencyKey.objects.update_or_create(
                key=key_uuid,
                defaults={
                    "path": request.path[:255],
                    "request_hash": request_hash,
                    "response_status": response.status_code,
                    "response_body": body_dict,
                },
            )

        return response

    return wrapper
