"""Данные «что может человек» для MSW-моков Платформы (ДОСТ-1) из настоящего расчёта BFF.

Файл `web/src/mocks/fixtures/capabilities.generated.json` — каталог (группы, строки, действия, тексты, условия) и для каждой
роли каталога (две системные и шаблоны) — какие действия включены. Моки складывают роли сотрудника так же, как BFF складывает
действия, и не пишут каталог второй раз руками. Руками не правится: `make -C apps/platform rbac`; `--check` сверяет файл.

Использование (из apps/platform/bff): `uv run python ../scripts/gen_capability_mocks.py [--check]`.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUTPUT = REPO / "apps" / "platform" / "web" / "src" / "mocks" / "fixtures" / "capabilities.generated.json"


def build() -> dict[str, object]:
    sys.path.insert(0, str(REPO / "apps" / "platform" / "bff"))
    from app.capabilities import CAPABILITIES, FREE_FOR_ALL, GROUPS, evaluate, held_by
    from app.capability_views import RoleView
    from app.rbac_generated import SYSTEM_ROLES, TEMPLATES

    roles: dict[str, dict[str, dict[str, bool]]] = {}
    for code, role in {**SYSTEM_ROLES, **TEMPLATES}.items():
        system = code in SYSTEM_ROLES
        view = RoleView(
            0, code, system, code if system else f"tpl:{code}", role["access"], role["restricted_fields"]
        )
        roles[code] = {key: state.on for key, state in evaluate(held_by([view])).items()}
    return {
        "free_for_all": FREE_FOR_ALL,
        "groups": GROUPS,
        "capabilities": CAPABILITIES,
        "roles": roles,
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print("capabilities.generated.json устарел — make -C apps/platform rbac и закоммитьте")
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
