"""Каталог «что может человек» (platform-capabilities.yaml, ДОСТ-1) сверяется с бэкендами.

Правило: экран не называет возможностью то, что бэкенд не проверяет, и не прячет то, что он проверяет.
Здесь — часть, которая смотрит в код бэкендов: каждый код действия существует (каталог ERP, EDS и CRM),
у каждого есть место, где его проверяют (поиск по исходникам), каждый код, который выдаёт `platform-rbac.yaml`,
назван каким-то действием. Расчёт «действие включено» против BFF, CRM (casbin) — в тестах Платформы и CRM.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from contracts_events import CONTRACTS
from jsonschema import Draft202012Validator

REPO = CONTRACTS.parent.parent
CAPS: dict[str, Any] = yaml.safe_load((CONTRACTS / "platform-capabilities.yaml").read_text(encoding="utf-8"))
RBAC: dict[str, Any] = yaml.safe_load((CONTRACTS / "platform-rbac.yaml").read_text(encoding="utf-8"))
SCHEMA = json.loads((CONTRACTS / "platform-capabilities.schema.json").read_text(encoding="utf-8"))
ERP_API: dict[str, Any] = yaml.safe_load((CONTRACTS / "openapi" / "erp-integration.yaml").read_text(encoding="utf-8"))
EDS_API: dict[str, Any] = yaml.safe_load((CONTRACTS / "openapi" / "eds.yaml").read_text(encoding="utf-8"))
BACKENDS = ("crm", "erp", "eds")


def actions() -> list[tuple[str, str, str, dict[str, Any]]]:
    return [
        (cap["key"], level, action["key"], action)
        for cap in CAPS["capabilities"]
        for level, items in cap["levels"].items()
        for action in items
    ]


def named(backend: str) -> set[str]:
    return {code for *_, action in actions() for code in action.get(backend, [])}


def granted(backend: str) -> set[str]:
    codes: set[str] = set()
    for resource in RBAC["resources"]:
        for listed in ((resource.get("backend") or {}).get(backend) or {}).values():
            codes.update(listed)
    for field in RBAC["restricted_fields"].values():
        codes.update(field["backend"].get(backend, []))
    return codes


def sources(root: str, skip: tuple[str, ...]) -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8", errors="ignore")
        for p in (REPO / root).rglob("*.py")
        if not any(part in p.parts for part in ("tests", "migrations", ".venv", "node_modules"))
        and not any(str(p).endswith(s) for s in skip)
        and not p.name.startswith("test_")
    }


def crm_catalog() -> set[str]:
    tree = ast.parse((REPO / "apps/crm/backend/app/security/rbac.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "CATALOG":
            return {f"{r}:{a}" for r, acts in ast.literal_eval(node.value).items() for a in acts}
    raise AssertionError("нет CATALOG в apps/crm/backend/app/security/rbac.py")


def test_the_file_matches_its_schema() -> None:
    Draft202012Validator(SCHEMA).validate(CAPS)


def test_keys_are_unique_and_groups_exist() -> None:
    keys = [c["key"] for c in CAPS["capabilities"]]
    assert len(keys) == len(set(keys))
    groups = {g["key"] for g in CAPS["groups"]}
    assert {c["group"] for c in CAPS["capabilities"]} <= groups
    assert 28 <= len(keys) <= 36
    pairs = [(c, a) for c, _, a, _ in actions()]
    assert len(pairs) == len(set(pairs))


def test_gates_use_existing_sections_and_levels() -> None:
    levels = {r["key"]: tuple(r.get("levels", ("read", "full"))) for r in RBAC["resources"]}
    for cap, _, key, action in actions():
        for gate in action["gates"]:
            for alternative in gate.split("|"):
                resource, _, level = alternative.partition(":")
                assert level in levels.get(resource, ()), (cap, key, alternative)


def test_texts_are_in_the_new_uzbek_alphabet_without_old_signs() -> None:
    uz = [a["text"]["uz"] for *_, a in actions()] + [c["name"]["uz"] for c in CAPS["capabilities"]]
    assert uz
    for text in uz:
        assert not re.search(r"[oOgG][‘’ʻ`']", text), text  # Oʻ Gʻ → Ö Ğ (решение владельца 2026-11-17)


def test_every_code_exists_in_its_backend() -> None:
    erp = set(ERP_API["components"]["schemas"]["ErpPermission"]["enum"])
    eds = set(EDS_API["components"]["schemas"]["EdsPermission"]["enum"])
    crm = crm_catalog()
    assert named("erp") <= erp
    assert named("eds") <= eds
    assert named("crm") <= crm


def test_no_code_the_roles_can_grant_is_left_unnamed() -> None:
    """«Скрыть то, что бэкенд разрешает» — нельзя: каждый код раздела и поля назван действием."""
    for backend in BACKENDS:
        assert sorted(granted(backend) - named(backend)) == [], backend


def test_erp_codes_are_enforced_somewhere_in_erp() -> None:
    code_files = sources("apps/erp/backend", ("accounts/constants.py",))
    for code in sorted(named("erp")):
        pattern = re.compile(
            r"[\"']" + re.escape(code) + r"[\"']|Permission\." + code.replace(".", "_").upper() + r"\b"
        )
        assert any(pattern.search(text) for text in code_files.values()), code


def test_eds_codes_are_enforced_somewhere_in_eds() -> None:
    code_files = sources("apps/eds/app", ("security/permissions.py",))
    for code in sorted(named("eds")):
        member = code.replace(".", "_").upper()
        pattern = re.compile(
            r"(Eds)?Permission\." + member + r"\b|\bP\." + member + r"\b|[\"']" + re.escape(code) + r"[\"']"
        )
        assert any(pattern.search(text) for text in code_files.values()), code


def test_crm_codes_are_enforced_somewhere_in_crm() -> None:
    code_files = sources("apps/crm/backend/app", ("security/rbac.py", "platform_roles_generated.py"))
    # Переписка и ответ в лиде проверяются по слову действия (`dialog("reply")`) или зоне (`INVOICED_ZONE`).
    by_word = {
        "leads:reply",
        "leads:note",
        "leads:assist",
        "chats:reply",
        "chats:note",
        "chats:assist",
        "chats:invoiced",
    }
    for code in sorted(named("crm")):
        resource, _, act = code.partition(":")
        if code in by_word:
            pattern = re.compile(
                r"dialog\(\s*[\"']"
                + act
                + r"[\"']|INVOICED_ZONE|[\"']"
                + resource
                + r"[\"']\s*,\s*[\"']"
                + act
                + r"[\"']"
            )
        else:
            pattern = re.compile(r"[\"']" + resource + r"[\"']\s*,\s*[\"']" + act + r"[\"']")
        assert any(pattern.search(text) for text in code_files.values()), code


def test_exceptional_actions_are_the_only_ones_needing_the_erp_superuser() -> None:
    assert [(c, a) for c, _, a, action in actions() if action.get("erp_superuser")] == [("exceptional", "force")]


@pytest.mark.parametrize("cap", [c["key"] for c in CAPS["capabilities"]])
def test_every_capability_has_a_level_with_actions(cap: str) -> None:
    levels = next(c for c in CAPS["capabilities"] if c["key"] == cap)["levels"]
    assert levels
    assert all(items for items in levels.values())
