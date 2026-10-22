"""Хранилище секретных полей издателя в кэше Django (Redis ERP) с TTL — код акцепта не пишется в outbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.cache import caches


class DjangoCacheStash:
    def __init__(self, *, ttl_seconds: int = 20 * 60, alias: str = "default", prefix: str = "rt_bus:secret:") -> None:
        self.ttl_seconds = ttl_seconds
        self.alias = alias
        self.prefix = prefix

    def put(self, event_id: str, values: Mapping[str, Any]) -> None:
        caches[self.alias].set(self.prefix + event_id, dict(values), timeout=self.ttl_seconds)

    def get(self, event_id: str) -> Mapping[str, Any] | None:
        value = caches[self.alias].get(self.prefix + event_id)
        return value if isinstance(value, dict) else None
