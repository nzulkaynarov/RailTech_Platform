"""Снимок сотрудника из событий identity (unit): терпимое чтение и пример из контракта."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bus.snapshots import UserDeactivated, UserEnvelope
from tests.conftest import user_snapshot

CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "events" / "identity" / "examples"


@pytest.mark.parametrize("name", ["user.created.v1.json", "user.updated.v1.json"])
def test_contract_examples_parse(name: str) -> None:
    envelope = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    snapshot = UserEnvelope.model_validate(envelope["data"]).user
    assert snapshot.crm_user_id == 7
    assert snapshot.is_active is True


def test_deactivated_example_parses() -> None:
    envelope = json.loads((CONTRACTS / "user.deactivated.v1.json").read_text(encoding="utf-8"))
    assert UserDeactivated.model_validate(envelope["data"]).crm_user_id == 7


def test_permissions_are_optional_and_sorted_unique() -> None:
    without = user_snapshot()
    del without["permissions"]
    assert UserEnvelope.model_validate({"user": without}).user.permissions_eds == []
    empty = user_snapshot(permissions={})
    assert UserEnvelope.model_validate({"user": empty}).user.permissions_eds == []
    many = user_snapshot(permissions={"eds": ["registry.read", "letters.read", "registry.read", "future.code"]})
    assert UserEnvelope.model_validate({"user": many}).user.permissions_eds == [
        "future.code",
        "letters.read",
        "registry.read",
    ]


def test_extra_fields_are_ignored_but_wrong_types_are_not() -> None:
    assert UserEnvelope.model_validate({"user": user_snapshot(new_field=1), "actor": {"type": "system"}}).user
    with pytest.raises(ValidationError):
        UserEnvelope.model_validate({"user": user_snapshot(is_active="yes please")})
    with pytest.raises(ValidationError):
        UserEnvelope.model_validate({"user": user_snapshot(updated_at="2026-10-26T08:00:00")})
