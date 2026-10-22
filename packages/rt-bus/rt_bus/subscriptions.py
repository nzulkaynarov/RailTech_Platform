"""Подписки v1: `packages/contracts/bus/subscriptions.yaml` (L5).

Издатель доставляет подписчику только свои события (по `source`) и не доставляет себе; выключенный подписчик
(`enabled: false`) новых доставок не получает. Файл перечитывается без перезапуска, когда меняется его mtime или размер:
новый подписчик подключается строкой в файле и секретом пары в окружении.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from .envelope import SERVICE_NAME_RE, source_for
from .errors import SubscriptionsError

logger = logging.getLogger("rt_bus.subscriptions")

SUBSCRIPTIONS_ENV = "RT_BUS_SUBSCRIPTIONS"
SUBSCRIPTIONS_FILE = Path("bus") / "subscriptions.yaml"

_ENDPOINT_RE = re.compile(r"^https?://\S+/bus/v1/events$")
_ENDPOINT_ENV_RE = re.compile(r"^RT_BUS_ENDPOINT_[A-Z0-9_]+$")
_MASK_RE = re.compile(r"^uz\.railtech\.[a-z0-9_.*?\[\]-]+\.v[0-9*]+$")


@dataclass(frozen=True)
class Subscriber:
    name: str
    endpoint: str
    types: tuple[str, ...]
    enabled: bool = True
    endpoint_env: str | None = None

    def url(self, environ: Mapping[str, str] | None = None) -> str:
        """Адрес приёмника: переменная `endpoint_env`, если задана и не пуста, иначе `endpoint` из файла."""
        env = os.environ if environ is None else environ
        if self.endpoint_env:
            override = (env.get(self.endpoint_env) or "").strip()
            if override:
                return override
        return self.endpoint

    def matches(self, event_type: str) -> bool:
        return any(fnmatchcase(event_type, mask) for mask in self.types)


@dataclass(frozen=True)
class Subscriptions:
    subscribers: tuple[Subscriber, ...]

    def get(self, name: str) -> Subscriber | None:
        return next((s for s in self.subscribers if s.name == name), None)

    def targets(self, event_type: str, source: str, publisher: str) -> list[Subscriber]:
        """Кому издатель доставляет событие: только свои (`source == rt://<publisher>`), не себе, включённым."""
        if source != source_for(publisher):
            return []
        return [s for s in self.subscribers if s.enabled and s.name != publisher and s.matches(event_type)]

    @classmethod
    def parse(cls, raw: Any, origin: str = "<subscriptions>") -> Subscriptions:
        def fail(message: str) -> SubscriptionsError:
            return SubscriptionsError(f"{origin}: {message}")

        if not isinstance(raw, Mapping):
            raise fail("not a mapping")
        if raw.get("version") != 1:
            raise fail("version must be 1")
        extra = set(raw) - {"version", "subscribers"}
        if extra:
            raise fail(f"unknown keys {sorted(extra)}")
        items = raw.get("subscribers")
        if not isinstance(items, list):
            raise fail("subscribers must be a list")
        seen: set[str] = set()
        out: list[Subscriber] = []
        for index, item in enumerate(items):
            where = f"subscribers[{index}]"
            if not isinstance(item, Mapping):
                raise fail(f"{where} is not a mapping")
            unknown = set(item) - {"name", "endpoint", "endpoint_env", "enabled", "types"}
            if unknown:
                raise fail(f"{where}: unknown keys {sorted(unknown)}")
            name = item.get("name")
            if not isinstance(name, str) or not SERVICE_NAME_RE.match(name):
                raise fail(f"{where}.name must match {SERVICE_NAME_RE.pattern}")
            if name in seen:
                raise fail(f"{where}.name {name!r} is not unique")
            seen.add(name)
            endpoint = item.get("endpoint")
            if not isinstance(endpoint, str) or not _ENDPOINT_RE.match(endpoint):
                raise fail(f"{where}.endpoint must be http(s)://…/bus/v1/events")
            endpoint_env = item.get("endpoint_env")
            if endpoint_env is not None and (
                not isinstance(endpoint_env, str) or not _ENDPOINT_ENV_RE.match(endpoint_env)
            ):
                raise fail(f"{where}.endpoint_env must match {_ENDPOINT_ENV_RE.pattern}")
            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                raise fail(f"{where}.enabled must be boolean")
            types = item.get("types")
            if not isinstance(types, list) or not types:
                raise fail(f"{where}.types must be a non-empty list")
            for mask in types:
                if not isinstance(mask, str) or not _MASK_RE.match(mask):
                    raise fail(f"{where}.types: {mask!r} is not a mask uz.railtech.<…>.v<N>")
            out.append(Subscriber(name, endpoint, tuple(types), enabled, endpoint_env))
        return cls(tuple(out))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Subscriptions:
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SubscriptionsError(f"{path}: not readable: {exc}") from exc
        return cls.parse(raw, str(path))


def resolve_subscriptions_path(value: str | os.PathLike[str] | None, contracts_dir: Path | None) -> Path:
    """Файл подписок: параметр → `RT_BUS_SUBSCRIPTIONS` → `<контракты>/bus/subscriptions.yaml` рядом с `events/`."""
    raw = value if value is not None else os.environ.get(SUBSCRIPTIONS_ENV)
    if raw:
        return Path(raw)
    if contracts_dir is not None:
        candidate = contracts_dir.parent / SUBSCRIPTIONS_FILE
        if candidate.is_file():
            return candidate
    raise SubscriptionsError(f"subscriptions file not found (parameter or {SUBSCRIPTIONS_ENV})")


class SubscriptionsSource:
    """Подписки из файла с перечитыванием по mtime/размеру. Битый файл после правки — остаются прежние, ошибка в лог."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._current: Subscriptions | None = None

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def current(self) -> Subscriptions:
        stamp = self._file_stamp()
        with self._lock:
            if self._current is not None and stamp == self._stamp:
                return self._current
            try:
                loaded = Subscriptions.load(self.path)
            except SubscriptionsError:
                if self._current is None:
                    raise
                logger.exception("rt_bus_subscriptions_reload_failed", extra={"path": str(self.path)})
                self._stamp = stamp
                return self._current
            if self._current is not None:
                logger.info(
                    "rt_bus_subscriptions_reloaded",
                    extra={"path": str(self.path), "subscribers": [s.name for s in loaded.subscribers]},
                )
            self._current, self._stamp = loaded, stamp
            return loaded
