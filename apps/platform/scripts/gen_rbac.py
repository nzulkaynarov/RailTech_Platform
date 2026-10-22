"""Генератор RBAC Платформы из `packages/contracts/platform-rbac.yaml` (PLT-11).

Контракт — единственный источник матрицы ролей, секции `menu` и полей с ограничением (ADR-0011,
docs/architecture/platform-bff.md §6). Из него получаются два файла, руками они не правятся:

- `apps/platform/bff/app/rbac_generated.py` — данные для BFF (`app/rbac.py` считает по ним доступ);
- `apps/platform/web/src/app/rbac.generated.ts` — данные и чистые функции для SPA.

Использование (из apps/platform/bff): `uv run python ../scripts/gen_rbac.py [--check]`;
через make: `make -C apps/platform rbac` и `rbac-check`; `--check` не пишет файлы, а сверяет их.
Вывод рассчитан на `ruff format` и `prettier` (printWidth 100): `make check-platform` проверяет оба.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "packages" / "contracts" / "platform-rbac.yaml"
SCHEMA = REPO / "packages" / "contracts" / "platform-rbac.schema.json"
PY_OUTPUT = REPO / "apps" / "platform" / "bff" / "app" / "rbac_generated.py"
TS_OUTPUT = REPO / "apps" / "platform" / "web" / "src" / "app" / "rbac.generated.ts"

WIDTH = 100
LANGS = ("ru", "uz", "en")


def load() -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(spec)
    return spec


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _check_references(spec: dict[str, Any]) -> None:
    """Пункты меню ссылаются только на существующие разделы матрицы."""
    keys = {r["key"] for r in spec["resources"]}
    for module, items in spec["menu"].items():
        for item, sections in items.items():
            unknown = [s for s in sections if s not in keys]
            if unknown:
                raise SystemExit(f"menu.{module}.{item}: нет разделов {unknown} в resources")
    for r in spec["resources"]:
        if r["module"] not in spec["menu"]:
            raise SystemExit(f"{r['key']}: модуль {r['module']} без секции menu")


# --- Python -----------------------------------------------------------------------------------


def _py_tuple(prefix: str, items: list[str], suffix: str = "") -> str:
    """`prefix("a", "b")suffix` одной строкой, если влезает, иначе по элементу на строке (ruff)."""
    indent = len(prefix) - len(prefix.lstrip())
    tail = "," if len(items) == 1 else ""
    one = f"{prefix}({', '.join(items)}{tail}){suffix}"
    if len(one) <= WIDTH:
        return one
    inner = "".join(f"{' ' * (indent + 4)}{it},\n" for it in items)
    return f"{prefix}(\n{inner}{' ' * indent}){suffix}"


def render_py(spec: dict[str, Any]) -> str:
    roles = list(spec["roles"])
    modules = list(spec["menu"])
    lines: list[str] = [
        '"""Матрица ролей Платформы. ГЕНЕРИРУЕТСЯ — не править руками (PLT-11).',
        "",
        f"Источник: packages/contracts/platform-rbac.yaml (version {spec['version']}).",
        "Пересоздание: `make -C apps/platform rbac`; `tests/test_rbac_generated.py` и",
        "`make check-platform` сверяют файл с контрактом. Логика доступа — `app/rbac.py`.",
        '"""',
        "",
        "from typing import Final, Literal",
        "",
        "RoleCode = Literal[" + ", ".join(_q(r) for r in roles) + "]",
        "ModuleCode = Literal[" + ", ".join(_q(m) for m in modules) + "]",
        'Level = Literal["full", "read", "hidden"]',
        "",
        "# Порядок ролей и модулей — как в контракте (модули рейла показываются в этом порядке).",
    ]
    lines.append(_py_tuple("ROLES: Final[tuple[RoleCode, ...]] = ", [_q(r) for r in roles]))
    lines.append(_py_tuple("MODULES: Final[tuple[ModuleCode, ...]] = ", [_q(m) for m in modules]))
    lines += ["", "# Названия ролей (ru/uz/en)."]
    lines.append("ROLE_NAMES: Final[dict[RoleCode, dict[str, str]]] = {")
    for r in roles:
        names = ", ".join(f"{_q(lang)}: {_q(spec['roles'][r]['name'][lang])}" for lang in LANGS)
        entry = f"    {_q(r)}: {{{names}}},"
        if len(entry) <= WIDTH:
            lines.append(entry)
        else:
            lines.append(f"    {_q(r)}: {{")
            lines += [
                f"        {_q(lang)}: {_q(spec['roles'][r]['name'][lang])}," for lang in LANGS
            ]
            lines.append("    },")
    lines.append("}")
    lines += [
        "",
        "# Роли ERP и права поверх шаблонов, которые CRM выдаёт роли Платформы",
        "# (docs/architecture/integration-map.md §4).",
        "# Пустой кортеж у ADMIN: суперпользователь ERP, роли ERP не нужны.",
    ]
    lines.append("ERP_ROLE_CODES: Final[dict[RoleCode, tuple[str, ...]]] = {")
    for r in roles:
        lines.append(
            _py_tuple(f"    {_q(r)}: ", [_q(c) for c in spec["roles"][r]["erp_role_codes"]], ",")
        )
    lines.append("}")
    lines.append("ERP_EXTRA_PERMISSIONS: Final[dict[RoleCode, tuple[str, ...]]] = {")
    for r in roles:
        perms = [_q(c) for c in spec["roles"][r]["erp_extra_permissions"]]
        lines.append(_py_tuple(f"    {_q(r)}: ", perms, ","))
    lines.append("}")
    lines += ["", "# Раздел матрицы -> модуль."]
    lines.append("RESOURCE_MODULE: Final[dict[str, ModuleCode]] = {")
    lines += [f"    {_q(r['key'])}: {_q(r['module'])}," for r in spec["resources"]]
    lines.append("}")
    lines += [
        "",
        "# Матрица SPEC-v3 §4.2: раздел -> роль -> уровень. У нескольких ролей берётся максимум.",
        "ACCESS: Final[dict[str, dict[RoleCode, Level]]] = {",
    ]
    for r in spec["resources"]:
        lines.append(f"    {_q(r['key'])}: {{")
        lines += [f"        {_q(role)}: {_q(r['access'][role])}," for role in roles]
        lines.append("    },")
    lines.append("}")
    lines += [
        "",
        "# Меню (Q-PLT-12-2): модуль -> пункт -> разделы; пункт виден, если виден любой из них.",
        "MENU: Final[dict[ModuleCode, dict[str, tuple[str, ...]]]] = {",
    ]
    for module, items in spec["menu"].items():
        lines.append(f"    {_q(module)}: {{")
        for item, sections in items.items():
            lines.append(_py_tuple(f"        {_q(item)}: ", [_q(s) for s in sections], ","))
        lines.append("    },")
    lines.append("}")
    lines += [
        "",
        "# Поля с ограничением (SPEC-v3 §4.2): группа -> роли, которым она видна.",
        "RESTRICTED_FIELDS: Final[dict[str, tuple[RoleCode, ...]]] = {",
    ]
    for name, field in spec["restricted_fields"].items():
        lines.append(_py_tuple(f"    {_q(name)}: ", [_q(r) for r in field["visible_to"]], ","))
    lines.append("}")
    return "\n".join(lines) + "\n"


# --- TypeScript -------------------------------------------------------------------------------


def _ts_arr(indent: int, items: list[str]) -> str:
    """`["a", "b"]` одной строкой, если влезает (prettier), иначе по элементу на строке."""
    one = "[" + ", ".join(items) + "]"
    if indent + len(one) + 1 <= WIDTH:
        return one
    pad = " " * (indent + 2)
    return "[\n" + "".join(f"{pad}{it},\n" for it in items) + " " * indent + "]"


def _ts_key(name: str) -> str:
    ident = name.replace("_", "a").isalnum() and not name[0].isdigit()
    return name if ident else _q(name)


TS_HELPERS = """\
const RANK: Record<AccessLevel, number> = { hidden: 0, read: 1, full: 2 };

/** Уровень раздела у набора ролей: максимум по ролям (full > read > hidden). */
export function levelFor(roles: readonly RoleCode[], resource: ResourceKey): AccessLevel {
  let best: AccessLevel = "hidden";
  for (const role of roles) {
    const level: AccessLevel = RESOURCES[resource].access[role];
    if (RANK[level] > RANK[best]) best = level;
  }
  return best;
}

/** Раздел виден (read или full). */
export function canSee(roles: readonly RoleCode[], resource: ResourceKey): boolean {
  return levelFor(roles, resource) !== "hidden";
}

/** Действие в разделе разрешено: `need` = "read" — чтение, "full" — изменение. */
export function allows(
  roles: readonly RoleCode[],
  resource: ResourceKey,
  need: Exclude<AccessLevel, "hidden"> = "read",
): boolean {
  return RANK[levelFor(roles, resource)] >= RANK[need];
}

/** Модули рейла в порядке показа: виден хотя бы один раздел модуля. */
export function visibleModules(roles: readonly RoleCode[]): ModuleCode[] {
  return MODULES.filter((module) =>
    (Object.keys(RESOURCES) as ResourceKey[]).some(
      (key) => RESOURCES[key].module === module && canSee(roles, key),
    ),
  );
}

/** Пункт меню виден, если виден хотя бы один из его разделов (`any_of`). */
export function menuItemVisible(
  roles: readonly RoleCode[],
  module: ModuleCode,
  item: string,
): boolean {
  const sections = (MENU[module] as Record<string, readonly ResourceKey[]>)[item];
  return sections?.some((key) => canSee(roles, key)) ?? false;
}

/** Видимые пункты меню модуля в порядке контракта. */
export function visibleMenuItems(roles: readonly RoleCode[], module: ModuleCode): string[] {
  return Object.keys(MENU[module]).filter((item) => menuItemVisible(roles, module, item));
}

/** Группы полей с ограничением, видимые хотя бы одной из ролей. */
export function visibleRestrictedFields(roles: readonly RoleCode[]): RestrictedField[] {
  return (Object.keys(RESTRICTED_FIELDS) as RestrictedField[]).filter((field) =>
    roles.some((role) => (RESTRICTED_FIELDS[field] as readonly RoleCode[]).includes(role)),
  );
}
"""


def render_ts(spec: dict[str, Any]) -> str:
    roles = list(spec["roles"])
    modules = list(spec["menu"])
    out: list[str] = [
        "// ГЕНЕРИРУЕТСЯ — не править руками (PLT-11).",
        f"// Источник: packages/contracts/platform-rbac.yaml (version {spec['version']}).",
        "// Пересоздание: make -C apps/platform rbac; make check-platform сверяет файл с контрактом",
        "// Матрица, меню и поля с ограничением — один источник с BFF (bff/app/rbac_generated.py).",
        "",
        "export const ROLES = " + _ts_arr(0, [_q(r) for r in roles]) + " as const;",
        "export type RoleCode = (typeof ROLES)[number];",
        "",
        "export const MODULES = " + _ts_arr(0, [_q(m) for m in modules]) + " as const;",
        "export type ModuleCode = (typeof MODULES)[number];",
        "",
        'export type AccessLevel = "full" | "read" | "hidden";',
        "",
        "export const ROLE_NAMES: Record<RoleCode, { ru: string; uz: string; en: string }> = {",
    ]
    for r in roles:
        out.append(f"  {r}: {{")
        out += [f"    {lang}: {_q(spec['roles'][r]['name'][lang])}," for lang in LANGS]
        out.append("  },")
    out += [
        "};",
        "",
        "/** Роли ERP, которые CRM выдаёт роли Платформы (docs/architecture/integration-map.md §4); у ADMIN пусто: суперпользователь ERP. */",
        "export const ERP_ROLE_CODES = {",
    ]
    for r in roles:
        out.append(
            f"  {r}: {_ts_arr(2 + len(r) + 2, [_q(c) for c in spec['roles'][r]['erp_role_codes']])},"
        )
    out += [
        "} as const satisfies Record<RoleCode, readonly string[]>;",
        "",
        "/** Права ERP поверх шаблонов ролей ERP. */",
        "export const ERP_EXTRA_PERMISSIONS = {",
    ]
    for r in roles:
        perms = [_q(c) for c in spec["roles"][r]["erp_extra_permissions"]]
        out.append(f"  {r}: {_ts_arr(2 + len(r) + 2, perms)},")
    out += [
        "} as const satisfies Record<RoleCode, readonly string[]>;",
        "",
        "/** Матрица SPEC-v3 §4.2: раздел -> модуль и уровень по каждой роли. */",
    ]
    out.append("export const RESOURCES = {")
    for r in spec["resources"]:
        out.append(f"  {_ts_key(r['key'])}: {{")
        out.append(f"    module: {_q(r['module'])},")
        out.append("    access: {")
        out += [f"      {role}: {_q(r['access'][role])}," for role in roles]
        out.append("    },")
        out.append("  },")
    out += [
        "} as const satisfies Record<string, { module: ModuleCode; access: Record<RoleCode, AccessLevel> }>;",
        "export type ResourceKey = keyof typeof RESOURCES;",
        "",
        "/** Меню (Q-PLT-12-2): модуль -> пункт -> разделы матрицы (виден любой из них). */",
        "export const MENU = {",
    ]
    for module, items in spec["menu"].items():
        out.append(f"  {_ts_key(module)}: {{")
        for item, sections in items.items():
            arr = _ts_arr(4, [_q(s) for s in sections])
            out.append(f"    {_ts_key(item)}: {arr},")
        out.append("  },")
    out += ["} as const satisfies Record<ModuleCode, Record<string, readonly ResourceKey[]>>;", ""]
    out.append("/** Поля с ограничением (SPEC-v3 §4.2): группа -> роли, которым она видна. */")
    out.append("export const RESTRICTED_FIELDS = {")
    for name, field in spec["restricted_fields"].items():
        arr = _ts_arr(2 + len(name) + 2, [_q(r) for r in field["visible_to"]])
        out.append(f"  {_ts_key(name)}: {arr},")
    out += [
        "} as const satisfies Record<string, readonly RoleCode[]>;",
        "export type RestrictedField = keyof typeof RESTRICTED_FIELDS;",
        "",
        TS_HELPERS.rstrip("\n"),
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только сверить файлы с контрактом")
    args = parser.parse_args()
    spec = load()
    _check_references(spec)
    targets = {PY_OUTPUT: render_py(spec), TS_OUTPUT: render_ts(spec)}
    if args.check:
        stale = [p for p, text in targets.items() if not p.exists() or p.read_text("utf-8") != text]
        for p in stale:
            sys.stderr.write(f"{p.relative_to(REPO)} устарел: make -C apps/platform rbac\n")
        return 1 if stale else 0
    for path, text in targets.items():
        path.write_text(text, encoding="utf-8")
        sys.stdout.write(f"rbac -> {path.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
