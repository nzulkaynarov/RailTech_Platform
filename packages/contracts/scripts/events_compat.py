"""Проверка совместимости схем событий rt_bus с базой (L8, ADR-0016).

    uv run python scripts/events_compat.py [--base REF]

Сравнивает каждую схему events/**/*.json (кроме examples/) и bus/subscriptions.schema.json с той же схемой в REF
(`git show REF:<путь>`; по умолчанию переменная CONTRACTS_BASE_REF, иначе точка ответвления HEAD от origin/main).
Файла или каталога в базе нет — новое, не ломающее. $ref (в том числе на _defs.vN.json) разворачиваются в обеих
версиях до сравнения.

В пределах vN допустимы только новые необязательные поля (в `properties`), новые типы (файлы) и новые определения
`$defs`; аннотации (title, description, examples, x-*) не сравниваются. Всё прочее — ломающее (код выхода 1), и сужение,
и расширение: удаление или переименование поля, любая смена type, enum, const, format, pattern, границ, required (новое
обязательное или снятое), additionalProperties, вариантов oneOf/anyOf/allOf, условий if/then/else/not, удаление файла
или определения. Причина: приёмник терпим только к лишним полям (L10), а значение вне enum или поле без
обязательности у старого подписчика — 422 и dead. Ломающее делается только новым файлом v(N+1) с двойной публикацией
на переходе. Код выхода 2 — базу не прочитать (нет ссылки: git fetch origin main).
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


def default_base() -> str:
    """База по умолчанию: CONTRACTS_BASE_REF (CI задаёт явно), иначе точка ответвления от origin/main.

    Локально ветка часто отстаёт от main: сравнение с вершиной origin/main видело бы чужие слитые изменения как
    «удалённые» (ложный красный) и заставляло бы делать merge main ради зелёного. Точка ответвления сравнивает только
    свои изменения; итог слияния с main проверяет CI на PR (база — вершина main). Нет общей истории (мелкий клон) —
    вершина origin/main (DECISIONS 2026-10-28).
    """
    env = os.environ.get("CONTRACTS_BASE_REF")
    if env:
        return env
    try:
        return _git("merge-base", "HEAD", DEFAULT_BASE).strip() or DEFAULT_BASE
    except subprocess.CalledProcessError:
        return DEFAULT_BASE


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


def _fmt(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def compare(old: Any, new: Any, at: str, out: list[str]) -> None:
    """Добавляет в out описание каждого изменения new относительно old, кроме допустимых в vN (L8, L10).

    Допустимо только: новое необязательное поле в `properties`, новое определение в `$defs`, аннотации
    (title, description, examples, x-*). Всё остальное — и сужение, и расширение — ломает старого подписчика или
    издателя (приёмник терпим только к лишним полям: additionalProperties, L10) и требует v(N+1).
    """
    o, n = _norm(old), _norm(new)
    if o == n:
        return
    if "$recursive" in o or "$recursive" in n:
        out.append(f"{at}: изменена рекурсивная ссылка")
        return

    for key in sorted((set(o) | set(n)) - IGNORED):
        if key.startswith("x-"):
            continue
        ov, nv = o.get(key), n.get(key)
        if key == "properties":
            oprops, nprops = ov or {}, nv or {}
            for name in oprops:
                if name not in nprops:
                    out.append(f"{at}/properties/{name}: поле удалено или переименовано")
                else:
                    compare(oprops[name], nprops[name], f"{at}/properties/{name}", out)
            # Новые поля допустимы, если не обязательные — это проверяет required ниже.
        elif key == "$defs":
            odefs, ndefs = ov or {}, nv or {}
            for name in odefs:
                if name not in ndefs:
                    out.append(f"{at}/$defs/{name}: определение удалено")
                else:
                    compare(odefs[name], ndefs[name], f"{at}/$defs/{name}", out)
        elif key == "required":
            added = sorted(set(nv or []) - set(ov or []))
            removed = sorted(set(ov or []) - set(nv or []))
            out += [f"{at}: новое обязательное поле «{name}»" for name in added]
            out += [f"{at}: поле «{name}» стало необязательным" for name in removed]
        elif key == "enum":
            if ov is None or nv is None:
                out.append(f"{at}: enum {_fmt(ov)} → {_fmt(nv)}")
            else:
                lost = [v for v in ov if v not in nv]
                gained = [v for v in nv if v not in ov]
                if lost:
                    out.append(f"{at}: сужение enum, убраны {_fmt(lost)}")
                if gained:
                    out.append(f"{at}: расширение enum {_fmt(gained)} — старый подписчик отклонит (422)")
        elif key == "type":
            if _type_set(ov) != _type_set(nv):
                out.append(f"{at}: смена типа {_fmt(ov)} → {_fmt(nv)}")
        elif key in SUBSCHEMA_MAPS:
            for name in sorted(set(ov or {}) | set(nv or {})):
                if name not in (ov or {}) or name not in (nv or {}):
                    out.append(f"{at}/{key}/{name}: добавлено или удалено")
                else:
                    compare(ov[name], nv[name], f"{at}/{key}/{name}", out)
        elif key in SUBSCHEMA_LISTS:
            if ov is None or nv is None or len(ov) != len(nv):
                out.append(f"{at}/{key}: варианты добавлены или удалены ({_len(ov)} → {_len(nv)})")
            else:
                for i, (ob, nb) in enumerate(zip(ov, nv, strict=True)):
                    compare(ob, nb, f"{at}/{key}/{i}", out)
        elif key in SUBSCHEMA:
            if ov in (None, True) and nv in (None, True):
                continue  # отсутствие и true равнозначны
            if key == "additionalProperties" and (ov is False) != (nv is False):
                out.append(f"{at}: additionalProperties {_fmt(ov)} → {_fmt(nv)}")
            elif ov is None or nv is None:
                out.append(f"{at}/{key}: добавлено или удалено ({_fmt(ov)} → {_fmt(nv)})")
            else:
                compare(ov, nv, f"{at}/{key}", out)
        elif ov != nv:
            out.append(f"{at}: {key} {_fmt(ov)} → {_fmt(nv)}")


SUBSCHEMA = (
    "items",
    "contains",
    "propertyNames",
    "unevaluatedItems",
    "additionalProperties",
    "unevaluatedProperties",
    "if",
    "then",
    "else",
    "not",
)
SUBSCHEMA_MAPS = ("patternProperties", "dependentSchemas")
SUBSCHEMA_LISTS = ("oneOf", "anyOf", "allOf", "prefixItems")


def _type_set(t: Any) -> set[str] | None:
    if t is None:
        return None
    return {t} if isinstance(t, str) else set(t)


def _len(v: Any) -> str:
    return "нет" if v is None else str(len(v))


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
    ap.add_argument("--base", default=None)
    args = ap.parse_args(argv)
    args.base = args.base or default_base()
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
