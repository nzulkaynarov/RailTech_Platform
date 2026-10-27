"""Отпечаток части каталога, влияющей на `permissions.eds` (W13C-F4, Q-W13-A2-3)."""

import copy
import re
from collections.abc import Mapping
from typing import Any

from app.domain import platform_roles_generated as generated
from app.domain.platform_roles import eds_catalog_fingerprint

BACKEND: dict[str, dict[str, tuple[str, ...]]] = {
    "eds.inbox": {"read": ("letters.read",), "full": ("letters.read", "letters.register")},
    "eds.drafts": {"full": ("approvals.decide",)},
    "crm.leads": {},
}
ROLE_ACCESS: dict[str, dict[str, str]] = {
    "ADMIN": {"eds.inbox": "full", "eds.drafts": "full", "crm.leads": "full"},
    "MANAGER": {"eds.inbox": "read", "crm.leads": "full"},
}
SYSTEM = ("ADMIN", "MANAGER")


def _fp(
    backend: Mapping[str, Mapping[str, tuple[str, ...]]] = BACKEND,
    role_access: Mapping[str, Mapping[str, str]] = ROLE_ACCESS,
) -> str:
    return eds_catalog_fingerprint(backend, role_access, SYSTEM)


def test_real_catalog_gives_stable_sha256() -> None:
    first = eds_catalog_fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == eds_catalog_fingerprint()


def test_real_catalog_fingerprint_follows_generated_tables() -> None:
    explicit = eds_catalog_fingerprint(
        generated.EDS_BACKEND, generated.ROLE_ACCESS, generated.SYSTEM_ROLE_CODES
    )
    assert explicit == eds_catalog_fingerprint()


def test_new_eds_code_in_a_section_changes_it() -> None:
    changed: Any = copy.deepcopy(BACKEND)
    changed["eds.drafts"] = {"full": ("approvals.decide", "bus.manage")}
    assert _fp(changed) != _fp()


def test_new_code_on_read_level_changes_it() -> None:
    changed: Any = copy.deepcopy(BACKEND)
    changed["eds.inbox"]["read"] = ("letters.read", "registry.read")
    assert _fp(changed) != _fp()


def test_new_section_with_eds_codes_changes_it() -> None:
    changed: Any = copy.deepcopy(BACKEND)
    changed["admin"] = {"full": ("bus.manage",)}
    assert _fp(changed) != _fp()


def test_eds_result_of_system_role_changes_it() -> None:
    changed = copy.deepcopy(ROLE_ACCESS)
    changed["MANAGER"]["eds.drafts"] = "full"
    assert _fp(role_access=changed) != _fp()


def test_non_eds_edits_do_not_change_it() -> None:
    reordered: dict[str, dict[str, tuple[str, ...]]] = {
        "crm.leads": {},
        "eds.drafts": {"full": ("approvals.decide",)},
        "eds.inbox": {"full": ("letters.register", "letters.read"), "read": ("letters.read",)},
    }
    assert _fp(reordered) == _fp()
    # пустые уровни и разделы без кодов EDS — не часть отпечатка
    with_empty: Any = copy.deepcopy(BACKEND)
    with_empty["eds.drafts"]["read"] = ()
    with_empty["chats.internal"] = {}
    assert _fp(with_empty) == _fp()
    # матрица системной роли по разделам без кодов EDS (права CRM/ERP) отпечаток не двигает
    crm_only = copy.deepcopy(ROLE_ACCESS)
    crm_only["MANAGER"]["crm.leads"] = "read"
    crm_only["ADMIN"]["chats.internal"] = "full"
    assert _fp(role_access=crm_only) == _fp()


def test_duplicate_code_across_levels_is_not_a_change() -> None:
    changed: Any = copy.deepcopy(BACKEND)
    changed["eds.inbox"]["full"] = ("letters.read", "letters.register", "letters.read")
    assert _fp(changed) == _fp()
