"""Сгенерированное = контракт: Python и TypeScript из packages/contracts/platform-rbac.yaml (v2)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from app import rbac_generated as generated

REPO = Path(__file__).resolve().parents[4]
CONTRACT = REPO / "packages/contracts/platform-rbac.yaml"
BFF_CONTRACT = REPO / "packages/contracts/openapi/platform-bff.yaml"
GENERATOR = REPO / "apps/platform/scripts/gen_rbac.py"
PY_FILE = REPO / "apps/platform/bff/app/rbac_generated.py"
TS_FILE = REPO / "apps/platform/web/src/app/rbac.generated.ts"


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_rbac", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_rbac"] = module
    spec.loader.exec_module(module)
    return module


def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def test_python_file_is_fresh() -> None:
    gen = load_generator()

    assert gen.render_py(gen.load()) == PY_FILE.read_text(encoding="utf-8")


def test_typescript_file_is_fresh() -> None:
    gen = load_generator()

    assert gen.render_ts(gen.load()) == TS_FILE.read_text(encoding="utf-8")


def test_generator_check_mode_is_green() -> None:
    result = subprocess.run(  # noqa: S603 — запуск собственного генератора
        [sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_generated_data_equals_contract() -> None:
    spec = contract()
    resources = spec["resources"]

    assert list(generated.MODULES) == list(spec["menu"])
    assert list(generated.RESOURCE_MODULE) == [r["key"] for r in resources]
    for row in resources:
        assert generated.RESOURCE_MODULE[row["key"]] == row["module"]
        assert list(generated.RESOURCE_LEVELS[row["key"]]) == row.get("levels", ["read", "full"])
    assert {m: {i: list(s) for i, s in items.items()} for m, items in generated.MENU.items()} == (
        spec["menu"]
    )
    assert list(generated.RESTRICTED_FIELDS) == list(spec["restricted_fields"])
    assert {k: list(v) for k, v in generated.QUEUE.items()} == {
        k: [v["resource"], v["level"]] for k, v in spec["queue"].items()
    }
    for group, data in (
        ("system_roles", generated.SYSTEM_ROLES),
        ("templates", generated.TEMPLATES),
    ):
        assert list(data) == list(spec[group])
        for code, body in spec[group].items():
            assert data[code]["name"] == body["name"]
            assert data[code]["access"] == body["access"]
            assert sorted(data[code]["restricted_fields"]) == sorted(body["restricted_fields"])


def test_queue_kinds_equal_the_contract_enum() -> None:
    """Каждый вид `QueueItemKind` контракта BFF описан в секции `queue` каталога и наоборот."""
    bff = yaml.safe_load(BFF_CONTRACT.read_text(encoding="utf-8"))
    kinds = bff["components"]["schemas"]["QueueItemKind"]["enum"]

    assert list(generated.QUEUE) == kinds


def test_contracts_hold_exactly_one_role_catalog() -> None:
    """В packages/contracts ровно один каталог ролей (версия 2): переходных v1/v2 нет."""
    catalogs = sorted(p.name for p in (REPO / "packages/contracts").glob("platform-rbac*.yaml"))
    schemas = sorted(p.name for p in (REPO / "packages/contracts").glob("platform-rbac*.json"))

    assert catalogs == ["platform-rbac.yaml"]
    assert schemas == ["platform-rbac.schema.json"]
    assert contract()["version"] == 2


def test_typescript_carries_every_section_and_role_of_the_contract() -> None:
    """Разделы, пункты меню, поля, очередь, системные роли и шаблоны есть в TS-файле буквально."""
    spec = contract()
    text = TS_FILE.read_text(encoding="utf-8")

    for row in spec["resources"]:
        key = row["key"]
        assert (f'  "{key}": {{' if "." in key else f"  {key}: {{") in text, key
        assert json.dumps(row["label"]["ru"], ensure_ascii=False) in text, key
    for module, items in spec["menu"].items():
        for item, sections in items.items():
            for section in sections:
                assert f'"{section}"' in text, (module, item, section)
    for name in spec["restricted_fields"]:
        assert f"  {name}: {{" in text
    for kind in spec["queue"]:
        assert f"  {kind}: {{" in text
    for group in ("system_roles", "templates"):
        for code, body in spec[group].items():
            assert f"  {code}: {{" in text
            assert json.dumps(body["name"]["ru"], ensure_ascii=False) in text
