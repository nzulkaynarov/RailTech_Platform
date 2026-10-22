"""Сгенерированное = контракт: Python и TypeScript из packages/contracts/platform-rbac.yaml."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from app import rbac_generated as generated

REPO = Path(__file__).resolve().parents[4]
CONTRACT = REPO / "packages/contracts/platform-rbac.yaml"
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

    assert list(generated.ROLES) == list(spec["roles"])
    assert list(generated.MODULES) == list(spec["menu"])
    for role, body in spec["roles"].items():
        assert generated.ROLE_NAMES[role] == body["name"]
    assert list(generated.ACCESS) == [r["key"] for r in spec["resources"]]
    for row in spec["resources"]:
        assert generated.ACCESS[row["key"]] == row["access"]
        assert generated.RESOURCE_MODULE[row["key"]] == row["module"]
    assert {m: {i: list(s) for i, s in items.items()} for m, items in generated.MENU.items()} == (
        spec["menu"]
    )
    assert {k: list(v) for k, v in generated.RESTRICTED_FIELDS.items()} == {
        k: v["visible_to"] for k, v in spec["restricted_fields"].items()
    }


def test_typescript_carries_every_cell_of_the_contract() -> None:
    """Каждая ячейка матрицы и пункт меню присутствуют в TS-файле буквально."""
    spec = contract()
    text = TS_FILE.read_text(encoding="utf-8")

    for row in spec["resources"]:
        key = row["key"]
        block = text[text.index(f'"{key}": {{') if "." in key else text.index(f"  {key}: {{") :]
        block = block[: block.index("    },\n") + 1]
        for role, lvl in row["access"].items():
            assert f'{role}: "{lvl}"' in block, (key, role)
    for module, items in spec["menu"].items():
        for item, sections in items.items():
            for section in sections:
                assert f'"{section}"' in text, (module, item, section)
    for name, field in spec["restricted_fields"].items():
        line = next(ln for ln in text.splitlines() if ln.startswith(f"  {name}:"))
        assert all(f'"{r}"' in line for r in field["visible_to"])
