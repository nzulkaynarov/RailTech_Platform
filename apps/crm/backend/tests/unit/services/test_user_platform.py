"""Роли Платформы в патче пользователя (R-1): вычисляется, игнорируется; пустой набор — 422."""

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import RolesRequiredError, ValidationFailedError
from app.services.user_platform import checked_position, resolve_patch, resolve_requested
from app.services.user_views import UserPatch
from tests.platform_role_data import make_role


def test_chosen_roles_compute_crm_role_and_access_without_erp_role_codes() -> None:
    chosen = [make_role("DIRECTOR"), make_role("MANAGER")]
    patch = resolve_patch([], chosen, UserPatch())

    assert patch.roles == ["manager"]  # manager > viewer; бухгалтер без crm.leads — viewer (D1-8)
    assert patch.platform_access == ["crm", "erp"]
    assert patch.erp_role_codes == []  # права ERP — вычисленный набор, не системные роли


def test_manual_values_in_the_same_patch_are_overridden_while_roles_are_set() -> None:
    patch = resolve_patch(
        [],
        [make_role("DIRECTOR")],
        UserPatch(roles=["admin"], platform_access=["crm"], erp_role_codes=["FINANCE"]),
    )

    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (
        ["viewer"],
        ["crm", "erp"],
        [],
    )


def test_manual_edit_of_a_platform_managed_user_is_overridden_too() -> None:
    patch = resolve_patch(
        [make_role("MANAGER")], None, UserPatch(roles=["admin"], erp_role_codes=["HEAD"])
    )

    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (
        ["manager"],
        ["crm", "erp"],
        [],
    )


def test_unrelated_patch_of_a_platform_managed_user_keeps_the_computed_state() -> None:
    patch = resolve_patch([make_role("SUPPLY")], None, UserPatch(tg_user_id=5))

    assert patch.roles == ["viewer"]
    assert patch.erp_role_codes == []


async def test_an_empty_set_of_roles_is_refused_before_any_lookup() -> None:
    """R3-D-1: у сотрудника хотя бы одна роль; закрыть доступ — отключить (422 `roles_required`)."""
    with pytest.raises(RolesRequiredError) as caught:
        await resolve_requested(cast("AsyncSession", None), [])

    assert isinstance(caught.value, ValidationFailedError)  # 422, как прочие ошибки валидации
    assert caught.value.code == "roles_required"
    assert caught.value.details == {"field": "platform_role_ids"}


def test_old_behaviour_without_platform_roles_is_untouched() -> None:
    original = UserPatch(roles=["viewer"], platform_access=["crm", "erp"], erp_role_codes=["HEAD"])

    assert resolve_patch([], None, original) == original


def test_position_longer_than_120_is_a_validation_error() -> None:
    with pytest.raises(ValidationFailedError):
        checked_position("я" * 121)
    assert checked_position("  ") is None
