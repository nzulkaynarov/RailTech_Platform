"""Помощники доменных тестов: сотрудники по ролям каталога, события outbox, проверка ответов по схемам `eds.yaml`."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import text

from app.container import Container
from app.security.access_token import issue_access_token
from tests.conftest import ACCESS_SECRET
from tests.helpers import bearer, seed_employee

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi" / "eds.yaml").read_text(
        encoding="utf-8"
    )
)
ALL = [
    "letters.read",
    "letters.register",
    "letters.resolve",
    "memos.create",
    "memos.approve",
    "approvals.decide",
    "registry.read",
    "registry.export",
    "payments.confirm",
    "files.upload",
]


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    permissions: list[str]

    @property
    def headers(self) -> dict[str, str]:
        return bearer(issue_access_token(self.id, ACCESS_SECRET))


# Роли каталога (CONTRACTS §10.4); «Регистратор» — письма без прав директора.
ROSTER: dict[str, Person] = {
    "director": Person(3, "Рустам Директоров", ALL),
    "registrar": Person(4, "Регина Регистраторова", ["letters.read", "letters.register", "memos.create"]),
    "manager": Person(5, "Алия Каримова", ["letters.read", "registry.read", "memos.create", "files.upload"]),
    "accountant": Person(
        6,
        "Бахтиёр Бухгалтеров",
        ["letters.read", "registry.read", "registry.export", "payments.confirm", "memos.create"],
    ),
    "supplier": Person(11, "Сардор Снабженцев", ["registry.read", "memos.create"]),
    "engineer": Person(12, "Ильдар Инженеров", ["registry.read", "memos.create"]),
    # «Администратор» каталога: служебные записки и журнал шины (`admin: full` → `bus.manage`, W13-A2).
    "admin": Person(9, "Админ Админов", ["memos.create", "bus.manage"]),
    "nobody": Person(10, "Без Прав", []),
}


async def seed_staff(container: Container) -> dict[str, Person]:
    for person in ROSTER.values():
        await seed_employee(
            container,
            person.id,
            full_name=person.name,
            email=f"user{person.id}@example.com",
            permissions={"eds": person.permissions},
        )
    return ROSTER


def validate(schema: str, body: Any) -> None:
    """Тело соответствует `components.schemas.<schema>` из eds.yaml (OpenAPI 3.1 = JSON Schema 2020-12)."""
    wrapper = {"$ref": f"#/components/schemas/{schema}", "components": SPEC["components"]}
    Draft202012Validator(wrapper, format_checker=FormatChecker()).validate(body)


async def outbox(container: Container, event_type: str | None = None) -> list[dict[str, Any]]:
    """События EDS в outbox по порядку записи: `{"type", "subject", "data"}`."""
    async with container.session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT type, subject, envelope FROM rt_bus_outbox ORDER BY created_at, id"),
            )
        ).all()
    found = [{"type": t, "subject": s, "data": env["data"]} for t, s, env in rows]
    if event_type is None:
        return found
    full = f"uz.railtech.eds.{event_type}.v1"
    return [e for e in found if e["type"] == full]


def new_id() -> str:
    return str(uuid.uuid4())


def day(year: int, month: int, d: int, hour: int = 8) -> datetime:
    return datetime(year, month, d, hour, 0, tzinfo=UTC)


async def deliver_erp(client: Any, container: Container, envelope: dict[str, Any]) -> str | None:
    """Подписанная доставка события ERP приёмнику и обработка inbox (как задача очереди); итоговый статус."""
    from tests.conftest import BUS_SECRET_ERP_EDS
    from tests.helpers import signed

    headers, body = signed(envelope, publisher="erp", secret=BUS_SECRET_ERP_EDS)
    response = await client.post("/bus/v1/events", headers=headers, content=body)
    assert response.status_code == 200, response.text
    return await container.bus.process_inbox(envelope["id"])


def erp_event(name: str, **payload: Any) -> dict[str, Any]:
    """Пример события ERP из каталога контрактов с подменой полей `data.payload` и новым id."""
    import copy

    from tests.helpers import example

    envelope = copy.deepcopy(example(name))
    envelope["data"]["payload"].update(payload)
    return envelope
