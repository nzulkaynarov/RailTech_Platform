"""Помощники тестов: подписанные доставки шины, токены, засев проекции."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from rt_bus import new_event
from rt_bus.delivery import build_attempt

from app.bus.snapshots import UserEnvelope
from app.container import Container
from app.services import employees
from tests.conftest import BUS_SECRET_CRM_EDS, SSO_CURRENT, user_snapshot

EVENTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "events"


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def identity_event(
    kind: str,
    data: dict[str, Any],
    *,
    event_id: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Конверт `uz.railtech.identity.user.<kind>.v1` от CRM."""
    return new_event(
        type=f"uz.railtech.identity.user.{kind}.v1",
        data=data,
        source="rt://crm",
        subject=f"user/{data.get('crm_user_id') or data['user']['crm_user_id']}",
        event_id=event_id,
        time=when or datetime.now(UTC),
    ).to_dict()


def user_event(
    kind: str = "created", *, event_id: str | None = None, when: datetime | None = None, **changes: Any
) -> dict[str, Any]:
    return identity_event(
        kind,
        {"user": user_snapshot(**changes), "actor": {"type": "staff", "crm_user_id": 1}},
        event_id=event_id,
        when=when,
    )


def deactivated_event(crm_user_id: int = 7, *, when: datetime | None = None) -> dict[str, Any]:
    return identity_event(
        "deactivated",
        {"crm_user_id": crm_user_id, "reason": "Увольнение", "actor": {"type": "staff", "crm_user_id": 1}},
        when=when,
    )


def signed(
    envelope: dict[str, Any], *, publisher: str = "crm", secret: str = BUS_SECRET_CRM_EDS
) -> tuple[dict[str, str], bytes]:
    attempt = build_attempt(
        envelope,
        publisher=publisher,
        url="http://eds-api:8000/bus/v1/events",
        secret=secret,
        now=datetime.now(UTC),
    )
    return attempt.headers, attempt.body


def example(name: str) -> dict[str, Any]:
    """Пример события из каталога контрактов, например `erp/request.created.v1`."""
    domain, _, rest = name.partition("/")
    data: dict[str, Any] = json.loads((EVENTS / domain / "examples" / f"{rest}.json").read_text(encoding="utf-8"))
    data["id"] = str(uuid.uuid4())
    return data


def sso_token(
    sub: str | int = 7,
    *,
    secret: str = SSO_CURRENT,
    now: datetime | None = None,
    lifetime: int = 60,
    **claims: Any,
) -> str:
    issued = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": "crm",
        "aud": "eds",
        "sub": str(sub),
        "email": "someone@example.com",
        "name": "Someone",
        "permissions": ["letters.read"],
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=lifetime)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    payload.update(claims)
    return jwt.encode(payload, secret, algorithm="HS256")


async def seed_employee(container: Container, crm_user_id: int = 7, **changes: Any) -> None:
    """Сотрудник в проекции (как после `identity.user.created`)."""
    snapshot = UserEnvelope.model_validate({"user": user_snapshot(crm_user_id, **changes)}).user
    async with container.session_factory() as session, session.begin():
        await employees.apply_snapshot(session, snapshot, event_id=uuid.uuid4())


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
