"""Замещение CRM → EDS (SIGN-2, ADR-0024 п. 2): `user.deputy` в снимке сотрудника попадает в проекцию и переводит задачу
подписи, но прав заместителю не даёт (pg)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.container import Container
from app.services import signing_resolve
from tests.helpers import deactivated_event, seed_employee, user_event
from tests.test_bus_projection import employee, receive_and_process

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
DEPUTY_PERIOD = {"crm_user_id": 8, "date_from": "2026-11-09", "date_to": "2026-11-20"}


def snapshot(kind: str, minutes: int, **changes: Any) -> dict[str, Any]:
    moment = T0 + timedelta(minutes=minutes)
    return user_event(kind, when=moment, updated_at=moment.isoformat(), **changes)


async def test_deputy_period_is_projected_and_cleared_by_a_newer_snapshot(
    client: httpx.AsyncClient, container: Container
) -> None:
    await receive_and_process(client, container, snapshot("created", 0, deputy=DEPUTY_PERIOD))
    row = await employee(container)
    assert (row["deputy_crm_user_id"], row["deputy_from"], row["deputy_to"]) == (
        8,
        date(2026, 11, 9),
        date(2026, 11, 20),
    )

    await receive_and_process(client, container, snapshot("updated", 5, deputy=None))
    row = await employee(container)
    assert (row["deputy_crm_user_id"], row["deputy_from"], row["deputy_to"]) == (None, None, None)


async def test_snapshot_without_the_field_means_no_substitution(
    client: httpx.AsyncClient, container: Container
) -> None:
    await receive_and_process(client, container, snapshot("created", 0, deputy=DEPUTY_PERIOD))
    await receive_and_process(client, container, snapshot("updated", 5))  # CRM до SIGN-2 поле не публикует
    assert (await employee(container))["deputy_crm_user_id"] is None


async def test_older_snapshot_does_not_bring_a_substitution_back(
    client: httpx.AsyncClient, container: Container
) -> None:
    await receive_and_process(client, container, snapshot("created", 10, deputy=None))
    await receive_and_process(client, container, snapshot("updated", 5, deputy=DEPUTY_PERIOD))
    assert (await employee(container))["deputy_crm_user_id"] is None


async def test_period_without_a_deputy_keeps_the_holder_in_place(
    client: httpx.AsyncClient, container: Container
) -> None:
    """CRM оставляет период, если заместителя отключили: `crm_user_id = null` — замещающего нет."""
    period = {"crm_user_id": None, "date_from": "2026-11-09", "date_to": "2026-11-20"}
    await receive_and_process(client, container, snapshot("created", 0, deputy=period))
    row = await employee(container)
    assert row["deputy_crm_user_id"] is None and row["deputy_from"] == date(2026, 11, 9)


async def test_deactivation_drops_the_substitution(client: httpx.AsyncClient, container: Container) -> None:
    await receive_and_process(client, container, snapshot("created", 0, deputy=DEPUTY_PERIOD))
    await receive_and_process(client, container, deactivated_event(7, when=T0 + timedelta(minutes=9)))
    row = await employee(container)
    assert row["is_active"] is False and row["deputy_crm_user_id"] is None


async def test_projected_substitution_moves_the_signing_task_but_gives_the_deputy_no_rights(
    client: httpx.AsyncClient, container: Container
) -> None:
    from app.models import SigningAuthority

    await seed_employee(container, 8, full_name="Дилшод Замов", email="deputy@example.com")
    async with container.session_factory() as session, session.begin():
        session.add(
            SigningAuthority(
                crm_user_id=7,
                kinds=["letter_out"],
                basis="charter",
                valid_from=date(2026, 1, 1),
                created_by=1,
                created_at=T0,
                updated_at=T0,
            )
        )
    await receive_and_process(client, container, snapshot("updated", 1, deputy=DEPUTY_PERIOD))

    async with container.session_factory() as session:
        during = await signing_resolve.resolve(
            session, kind="letter_out", amount=Decimal("1.00"), currency="UZS", on_date=date(2026, 11, 10)
        )
        after = await signing_resolve.resolve(
            session, kind="letter_out", amount=None, currency=None, on_date=date(2026, 11, 21)
        )
    assert not during.resolved  # заместитель без собственного полномочия подписать не вправе
    assert {r.reason for r in during.rejected} == {"absent", "deputy_without_authority"}
    assert [c.signer.crm_user_id for c in after.candidates] == [7]
