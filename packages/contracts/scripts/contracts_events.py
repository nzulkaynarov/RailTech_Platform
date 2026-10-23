"""Общее для скриптов и тестов событий rt_bus: каталог типов, загрузка схем, разрешение $ref.

Раскладка (docs/architecture/CONTRACTS.md, раздел «Шина rt_bus», L2):
    events/envelope.v1.json                                  конверт CloudEvents
    events/<домен>/<сущность>.<действие>.v<N>.json           схема data типа uz.railtech.<домен>.<сущ>.<действие>.v<N>
    events/<домен>/_defs.v<N>.json                           общие определения домена (не тип)
    events/<домен>/examples/<сущность>.<действие>.v<N>.json  пример полного конверта
    events/asyncapi.yaml                                     AsyncAPI 3.0
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACTS = Path(__file__).resolve().parent.parent
EVENTS = CONTRACTS / "events"
BUS = CONTRACTS / "bus"
ENVELOPE = EVENTS / "envelope.v1.json"
DOMAINS = ("crm", "erp", "eds", "identity", "platform")
# Издатель домена v1: идентичность живёт в CRM (ADR-0015).
DOMAIN_SOURCE = {
    "crm": "rt://crm",
    "erp": "rt://erp",
    "eds": "rt://eds",
    "identity": "rt://crm",
    "platform": "rt://platform-bff",
}

SEGMENT = r"[a-z][a-z0-9_]*"
TYPE_FILE = re.compile(rf"^(?P<entity>{SEGMENT})\.(?P<action>{SEGMENT})\.v(?P<version>[1-9][0-9]*)\.json$")
DEFS_FILE = re.compile(r"^_defs\.v(?P<version>[1-9][0-9]*)\.json$")


@dataclass(frozen=True)
class EventType:
    domain: str
    entity: str
    action: str
    version: int

    @property
    def name(self) -> str:
        """uz.railtech.erp.quote.sent.v1"""
        return f"uz.railtech.{self.domain}.{self.entity}.{self.action}.v{self.version}"

    @property
    def stem(self) -> str:
        """quote.sent.v1"""
        return f"{self.entity}.{self.action}.v{self.version}"

    @property
    def path(self) -> Path:
        return EVENTS / self.domain / f"{self.stem}.json"

    @property
    def example(self) -> Path:
        return EVENTS / self.domain / "examples" / f"{self.stem}.json"

    @property
    def source(self) -> str:
        return DOMAIN_SOURCE[self.domain]

    @property
    def dataschema(self) -> str:
        return f"rt://contracts/events/{self.domain}/{self.entity}.{self.action}/v{self.version}"

    @property
    def class_name(self) -> str:
        """QuoteSentV1"""
        return f"{pascal(self.entity)}{pascal(self.action)}V{self.version}"


def pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


def event_types() -> list[EventType]:
    """Все типы по файлам events/<домен>/*.v<N>.json (без _defs и examples), в стабильном порядке."""
    found: list[EventType] = []
    for domain in DOMAINS:
        folder = EVENTS / domain
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.json")):
            if f.name.startswith("_"):
                continue
            m = TYPE_FILE.match(f.name)
            if not m:
                raise ValueError(f"{f}: имя не <сущность>.<действие>.v<N>.json (L2)")
            found.append(EventType(domain, m["entity"], m["action"], int(m["version"])))
    return found


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_files() -> list[Path]:
    """Все JSON-схемы шины: конверт, типы, _defs, подписки (без примеров)."""
    files = [p for p in sorted(EVENTS.rglob("*.json")) if "examples" not in p.relative_to(EVENTS).parts]
    return files + [BUS / "subscriptions.schema.json"]


def registry():  # noqa: ANN201 — referencing импортируется лениво (генератору не нужен)
    """Реестр referencing по $id всех схем: относительные $ref разрешаются как у файлов на диске."""
    from referencing import Registry, Resource

    resources = []
    for p in schema_files():
        doc = load_json(p)
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)
