"""Проверка совместимости схем событий rt_bus с базой (L8, ADR-0016).

    uv run python scripts/events_compat.py [--base REF]

Сравнивает каждую схему events/**/*.json (кроме examples/) и bus/subscriptions.schema.json с той же схемой в REF
(`git show REF:<путь>`; по умолчанию переменная CONTRACTS_BASE_REF или origin/main). Файла или каталога в базе
нет — новое, не ломающее. $ref (в том числе на _defs.vN.json) разворачиваются в обеих версиях до сравнения.

В пределах vN допустимы только добавления: новое необязательное поле, новый тип (файл), расширение enum, снятие
ограничений. Ломающее (код выхода 1): удаление или переименование поля; смена типа (кроме расширения);
новое обязательное поле; сужение enum, const, формата, шаблона, границ; ужесточение additionalProperties; удаление
файла типа или определения $defs; новые условия allOf/if/not. Ломающее делается только новым файлом v(N+1) с
двойной публикацией на переходе. Код выхода 2 — базу не прочитать (нет ссылки: git fetch origin main).
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACTS = Path(__file__).resolve().parent.parent
ROOTS = ("events", "bus")
DEFAULT_BASE = "origin/main"

Tree = Mapping[str, Any]  # путь от packages/contracts (posix) → разобранный JSON

IGNORED = {
    "title",
    "description",
    "examples",
    "default",
    "$comment",
    "$schema",
    "$id",
    "deprecated",
    "readOnly",
    "writeOnly",
    "contentMediaType",
    "contentEncoding",
}
LOWER = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties", "minContains")
UPPER = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties", "maxContains")
SUBSCHEMA = ("items", "contains", "propertyNames", "unevaluatedItems")


def is_schema_path(path: str) -> bool:
    parts = path.split("/")
    if not path.endswith(".json") or "examples" in parts:
        return False
    return parts[0] == "events" or path == "bus/subscriptions.schema.json"


# ─── загрузка деревьев ─────────────────────────────────────────────────────────────────────────


def working_tree() -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for root in ROOTS:
        for p in sorted((CONTRACTS / root).rglob("*.json")):
            rel = p.relative_to(CONTRACTS).as_posix()
            if is_schema_path(rel):
                tree[rel] = json.loads(p.read_text(encoding="utf-8"))
    return tree


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=CONTRACTS, check=True, capture_output=True, text=True).stdout


def git_tree(ref: str) -> dict[str, Any]:
    try:
        _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError as e:
        hint = "git fetch origin main или другая база в CONTRACTS_BASE_REF"
        raise SystemExit(f"events-compat: база {ref!r} не найдена — {hint}") from e
    prefix = _git("rev-parse", "--show-prefix").strip()  # packages/contracts/
    listed = _git("ls-tree", "-r", "--name-only", "--full-tree", ref, "--", *(prefix + r for r in ROOTS))
    tree: dict[str, Any] = {}
    for full in listed.splitlines():
        rel = full[len(prefix) :]
        if is_schema_path(rel):
            tree[rel] = json.loads(_git("show", f"{ref}:{full}"))
    return tree


# ─── разворачивание $ref ──────────────────────────────────────────────────────────────────────


def _pointer(doc: Any, pointer: str, where: str) -> Any:
    node = doc
    for raw in [p for p in pointer.lstrip("/").split("/") if p] if pointer else []:
        key = raw.replace("~1", "/").replace("~0", "~")
        try:
            node = node[int(key)] if isinstance(node, list) else node[key]
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ValueError(f"{where}: $ref указывает на несуществующее #{pointer}") from e
    return node


def deref(node: Any, path: str, tree: Tree, stack: tuple[str, ...] = ()) -> Any:
    """Копия схемы со всеми $ref (локальными и на файлы того же дерева), развёрнутыми на месте."""
    if isinstance(node, list):
        return [deref(x, path, tree, stack) for x in node]
    if not isinstance(node, dict):
        return node
    if isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        file_part, _, pointer = ref.partition("#")
        target_path = posixpath.normpath(posixpath.join(posixpath.dirname(path), file_part)) if file_part else path
        if target_path not in tree:
            raise ValueError(f"{path}: $ref {ref!r} — файла {target_path} нет")
        key = f"{target_path}#{pointer}"
        if key in stack:
            return {"$recursive": key}
        target = deref(_pointer(tree[target_path], pointer, path), target_path, tree, (*stack, key))
        siblings = {k: deref(v, path, tree, stack) for k, v in node.items() if k != "$ref"}
        if isinstance(target, dict):
            return {**target, **siblings}
        return target if not siblings else {"allOf": [target], **siblings}
    return {k: deref(v, path, tree, stack) for k, v in node.items()}


# ─── сравнение ────────────────────────────────────────────────────────────────────────────────


def _norm(s: Any) -> dict[str, Any]:
    if s is True or s is None:
        return {}
    if s is False:
        return {"not": {}}
    return s


def _types(s: Mapping[str, Any]) -> set[str] | None:
    t = s.get("type")
    if t is None:
        return None
    ts = {t} if isinstance(t, str) else set(t)
    return ts | {"integer"} if "number" in ts else ts


def _fmt(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def compare(old: Any, new: Any, at: str, out: list[str]) -> None:
    """Добавляет в out описание каждого ломающего изменения new относительно old (L8)."""
    o, n = _norm(old), _norm(new)
    if o == n:
        return
    if "$recursive" in o or "$recursive" in n:
        if o != n:
            out.append(f"{at}: изменена рекурсивная ссылка")
        return

    ot, nt = _types(o), _types(n)
    if nt is not None and (ot is None or not ot <= nt):
        out.append(f"{at}: смена типа {_fmt(o.get('type'))} → {_fmt(n.get('type'))}")

    if "const" in n and ("const" not in o or o["const"] != n["const"]):
        out.append(f"{at}: const {_fmt(o.get('const'))} → {_fmt(n['const'])}")
    if "enum" in n:
        allowed = o["enum"] if "enum" in o else ([o["const"]] if "const" in o else None)
        if allowed is None:
            out.append(f"{at}: добавлен enum {_fmt(n['enum'])} (сужение)")
        else:
            lost = [v for v in allowed if v not in n["enum"]]
            if lost:
                out.append(f"{at}: сужение enum, убраны {_fmt(lost)}")

    if n.get("format") and n.get("format") != o.get("format"):
        out.append(f"{at}: формат {_fmt(o.get('format'))} → {_fmt(n['format'])}")
    if "pattern" in n and n["pattern"] != o.get("pattern"):
        out.append(f"{at}: шаблон {_fmt(o.get('pattern'))} → {_fmt(n['pattern'])}")
    for k in LOWER:
        if k in n and (k not in o or n[k] > o[k]):
            out.append(f"{at}: {k} {_fmt(o.get(k))} → {_fmt(n[k])} (сужение)")
    for k in UPPER:
        if k in n and (k not in o or n[k] < o[k]):
            out.append(f"{at}: {k} {_fmt(o.get(k))} → {_fmt(n[k])} (сужение)")
    if "multipleOf" in n and n["multipleOf"] != o.get("multipleOf"):
        out.append(f"{at}: multipleOf {_fmt(o.get('multipleOf'))} → {_fmt(n['multipleOf'])}")
    if n.get("uniqueItems") and not o.get("uniqueItems"):
        out.append(f"{at}: добавлено uniqueItems")

    for name in sorted(set(n.get("required", [])) - set(o.get("required", []))):
        out.append(f"{at}: новое обязательное поле «{name}»")
    oprops, nprops = o.get("properties", {}), n.get("properties", {})
    for name in oprops:
        if name not in nprops:
            out.append(f"{at}/properties/{name}: поле удалено или переименовано")
        else:
            compare(oprops[name], nprops[name], f"{at}/properties/{name}", out)
    for key in ("additionalProperties", "unevaluatedProperties"):
        oa, na = o.get(key, True), n.get(key, True)
        if na is False and oa is not False:
            out.append(f"{at}: ужесточение {key} ({_fmt(oa)} → false)")
        elif na is not False:
            compare(oa, na, f"{at}/{key}", out)
    for name in sorted(set(o.get("patternProperties", {})) | set(n.get("patternProperties", {}))):
        compare(
            o.get("patternProperties", {}).get(name),
            n.get("patternProperties", {}).get(name),
            f"{at}/patternProperties/{name}",
            out,
        )

    for key in SUBSCHEMA:
        if key in o or key in n:
            compare(o.get(key), n.get(key), f"{at}/{key}", out)
    oprefix, nprefix = o.get("prefixItems", []), n.get("prefixItems", [])
    for i in range(max(len(oprefix), len(nprefix))):
        compare(
            oprefix[i] if i < len(oprefix) else None,
            nprefix[i] if i < len(nprefix) else None,
            f"{at}/prefixItems/{i}",
            out,
        )

    odefs, ndefs = o.get("$defs", {}), n.get("$defs", {})
    for name in odefs:
        if name not in ndefs:
            out.append(f"{at}/$defs/{name}: определение удалено")
        else:
            compare(odefs[name], ndefs[name], f"{at}/$defs/{name}", out)

    for key in ("oneOf", "anyOf"):
        if key not in n:
            continue
        if key not in o:
            out.append(f"{at}: добавлен {key} (сужение)")
            continue
        for i, branch in enumerate(o[key]):
            if not any(_clean(branch, nb) for nb in n[key]):
                out.append(f"{at}/{key}/{i}: вариант удалён или сужен")
    if "allOf" in n:
        for i, branch in enumerate(n["allOf"]):
            if not any(_clean(ob, branch) for ob in o.get("allOf", [])):
                out.append(f"{at}/allOf/{i}: новое или более строгое условие allOf")

    if "if" in n and n["if"] != o.get("if"):
        out.append(f"{at}: новое или изменённое условие if")
    for key in ("then", "else"):
        if key in o or key in n:
            compare(o.get(key), n.get(key), f"{at}/{key}", out)
    if "not" in n and n["not"] != o.get("not"):
        out.append(f"{at}: новое или изменённое условие not")

    odr, ndr = o.get("dependentRequired", {}), n.get("dependentRequired", {})
    for name, fields in ndr.items():
        extra = sorted(set(fields) - set(odr.get(name, [])))
        if extra:
            out.append(f"{at}/dependentRequired/{name}: новые обязательные {_fmt(extra)}")
    for name in sorted(set(o.get("dependentSchemas", {})) | set(n.get("dependentSchemas", {}))):
        compare(
            o.get("dependentSchemas", {}).get(name),
            n.get("dependentSchemas", {}).get(name),
            f"{at}/dependentSchemas/{name}",
            out,
        )

    unknown = sorted(k for k in (set(o) | set(n)) - KNOWN - IGNORED if not k.startswith("x-"))
    for k in unknown:
        if o.get(k) != n.get(k):
            out.append(f"{at}: изменено ключевое слово {k}, правило совместимости для него не задано")


KNOWN = {
    "type",
    "const",
    "enum",
    "format",
    "pattern",
    *LOWER,
    *UPPER,
    "multipleOf",
    "uniqueItems",
    "required",
    "properties",
    "additionalProperties",
    "unevaluatedProperties",
    "patternProperties",
    *SUBSCHEMA,
    "prefixItems",
    "$defs",
    "oneOf",
    "anyOf",
    "allOf",
    "if",
    "then",
    "else",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "$recursive",
}


def _clean(old: Any, new: Any) -> bool:
    probe: list[str] = []
    compare(old, new, "#", probe)
    return not probe


def check(base: Tree, head: Tree) -> list[str]:
    """Ломающие изменения head относительно base; пустой список — совместимо."""
    problems: list[str] = []
    for path in sorted(base):
        if path not in head:
            problems.append(f"{path}: файл удалён (ломающее; новый мажор — новым файлом v(N+1))")
    for path in sorted(head):
        new = deref(head[path], path, head)  # битая ссылка в новом — ошибка и без базы
        if path not in base:
            continue
        old = deref(base[path], path, base)
        found: list[str] = []
        compare(old, new, "#", found)
        problems += [f"{path} {msg}" for msg in found]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", default=os.environ.get("CONTRACTS_BASE_REF") or DEFAULT_BASE)
    args = ap.parse_args(argv)
    try:
        base = git_tree(args.base)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    head = working_tree()
    problems = check(base, head)
    if problems:
        print(f"events-compat: ломающие изменения относительно {args.base} (L8 — только новым файлом v(N+1)):")
        for p in problems:
            print(f"  - {p}")
        return 1
    added = len(set(head) - set(base))
    print(f"events-compat: совместимо с {args.base} ({len(head)} схем, новых {added})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
