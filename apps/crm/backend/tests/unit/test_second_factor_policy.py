"""DV-4b: the second factor is mandatory by effective permission sections, never by role names."""

import pytest

from app.domain import second_factor_policy as policy
from app.domain.platform_roles import RoleGrant, merge_access
from app.domain.platform_roles_generated import ROLE_ACCESS


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        ({}, False),
        ({"eds.payments": "full"}, True),
        ({"eds.payments": "read"}, False),
        ({"eds.memo.approve": "full"}, True),
        ({"eds.memo.approve": "read"}, False),
        ({"eds.drafts": "full"}, True),
        ({"eds.drafts": "read"}, False),
        ({"admin": "full"}, True),
        ({"admin": "read"}, False),
        ({"crm.leads": "full", "eds.projects": "full", "company.settings": "full"}, False),
    ],
)
def test_required_by_section_and_level(access: dict[str, str], expected: bool) -> None:
    assert policy.factor_required(access) is expected


def test_inactive_employee_is_not_asked() -> None:
    assert policy.factor_required({"admin": "full"}, is_active=False) is False


def test_union_of_roles_decides_not_a_single_role() -> None:
    # two roles, each below the line on its own: reading payments + full drafts is required only
    # through drafts; reading payments alone is not
    reader = RoleGrant({"eds.payments": "read"})
    drafter = RoleGrant({"eds.drafts": "full"})
    assert policy.factor_required(merge_access([reader])) is False
    assert policy.factor_required(merge_access([reader, drafter])) is True


def test_catalog_roles_follow_their_sections() -> None:
    """Today's catalogue: director, accountant, administrator and the pilot universal manager
    (holds `eds.payments: full`) are covered; the rest are not."""
    required = {code for code, access in ROLE_ACCESS.items() if policy.factor_required(access)}
    assert {"ADMIN", "DIRECTOR", "ACCOUNTANT", "MANAGER_ALL"} <= required
    assert not {"MANAGER", "SUPPLY", "ENGINEER", "REGISTRAR"} & required


def test_sections_are_listed_in_one_place() -> None:
    assert [s for s, _ in policy.FACTOR_REQUIRED_SECTIONS] == [
        "eds.payments",
        "eds.memo.approve",
        "eds.drafts",
        "admin",
    ]
    assert policy.required_sections({"admin": "full", "eds.payments": "full"}) == [
        "eds.payments",
        "admin",
    ]
