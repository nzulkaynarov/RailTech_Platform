"""Роли Платформы в патче пользователя (CRM-01): вычисляется, игнорируется, снимается."""

import pytest

from app.domain.errors import ValidationFailedError
from app.services.user_platform import checked_position, resolve_patch
from app.services.users import UserPatch


def test_chosen_roles_compute_crm_role_access_and_erp_roles() -> None:
    patch = resolve_patch([], UserPatch(platform_roles=["ACCOUNTANT", "DIRECTOR"]))

    assert patch.platform_roles == ["DIRECTOR", "ACCOUNTANT"]
    assert patch.roles == ["manager"]
    assert patch.platform_access == ["crm", "erp"]
    assert patch.erp_role_codes == ["FINANCE", "HEAD"]


def test_manual_values_in_the_same_patch_are_overridden_while_roles_are_set() -> None:
    patch = resolve_patch(
        [],
        UserPatch(
            platform_roles=["DIRECTOR"],
            roles=["admin"],
            platform_access=["crm"],
            erp_role_codes=["FINANCE"],
        ),
    )

    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (
        ["viewer"],
        ["crm", "erp"],
        ["HEAD"],
    )


def test_manual_edit_of_a_platform_managed_user_is_overridden_too() -> None:
    patch = resolve_patch(["MANAGER"], UserPatch(roles=["admin"], erp_role_codes=[]))

    assert patch.platform_roles is None
    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (
        ["manager"],
        ["crm", "erp"],
        ["VIEWER"],
    )


def test_unrelated_patch_of_a_platform_managed_user_keeps_the_computed_state() -> None:
    patch = resolve_patch(["SUPPLY"], UserPatch(tg_user_id=5))

    assert patch.roles == ["viewer"]
    assert patch.erp_role_codes == ["CATALOG_SUPPLY", "FULFILLMENT"]


def test_removing_all_roles_returns_the_least_privilege_defaults() -> None:
    patch = resolve_patch(["ADMIN", "MANAGER"], UserPatch(platform_roles=[]))

    assert patch.platform_roles == []
    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (["viewer"], ["crm"], [])


def test_removing_roles_with_explicit_manual_values_keeps_them() -> None:
    patch = resolve_patch(
        ["DIRECTOR"],
        UserPatch(
            platform_roles=[],
            roles=["manager"],
            platform_access=["crm", "erp"],
            erp_role_codes=["FINANCE"],
        ),
    )

    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (
        ["manager"],
        ["crm", "erp"],
        ["FINANCE"],
    )


def test_empty_list_for_a_user_without_roles_changes_nothing() -> None:
    patch = resolve_patch([], UserPatch(platform_roles=[], roles=["manager"]))

    assert (patch.roles, patch.platform_access, patch.erp_role_codes) == (["manager"], None, None)


def test_old_behaviour_without_platform_roles_is_untouched() -> None:
    original = UserPatch(roles=["viewer"], platform_access=["crm", "erp"], erp_role_codes=["HEAD"])

    assert resolve_patch([], original) == original


def test_foreign_role_code_is_a_validation_error() -> None:
    with pytest.raises(ValidationFailedError):
        resolve_patch([], UserPatch(platform_roles=["ROOT"]))


def test_position_longer_than_120_is_a_validation_error() -> None:
    with pytest.raises(ValidationFailedError):
        checked_position("я" * 121)
    assert checked_position("  ") is None
