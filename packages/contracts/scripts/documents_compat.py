"""Совместимость контракта документов с базой (ADR-0016, ADR-0020): тело документа и каталог переменных.

    uv run python scripts/documents_compat.py [--base REF]

Тела документов хранятся годами (выпущенный документ — снимок тела), поэтому правило обратное событиям: в пределах
мажора схема тела может только **расширяться** (новые узлы, новые необязательные атрибуты, новые значения enum),
а сужение — ломающее. Проверка по корпусу: каждое тело-пример базы (`documents/examples/*.json` в REF) обязано
проходить схему head. Кроме того:
- semver в `$comment` схемы (`semver X.Y.Z`) не убывает, а при любой правке схемы (кроме аннотаций) — растёт;
- мажор `properties.version.const` тела не меняется (мажор 2 — новый файл `body.v2.schema.json` с конвертером);
- коды переменных и блоков каталога не удаляются (документы ссылаются на них), виды не удаляются.
Файла в базе нет — новое, не ломающее. Код выхода 1 — ломающее, 2 — базу не прочитать.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parent.parent
DOCS = "documents"
BODY = f"{DOCS}/body.schema.json"
CATALOG = f"{DOCS}/variables.yaml"
DEFAULT_BASE = "origin/main"
_SEMVER = re.compile(r"semver (\d+)\.(\d+)\.(\d+)")
ANNOTATIONS = {"title", "description", "examples", "$comment", "default"}

Tree = Mapping[str, str]  # путь от packages/contracts → текст файла


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=CONTRACTS, check=True, capture_output=True, text=True).stdout


def git_tree(ref: str) -> dict[str, str]:
    try:
        _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"documents-compat: база {ref!r} не найдена — git fetch origin main") from e
    prefix = _git("rev-parse", "--show-prefix").strip()
    listed = _git("ls-tree", "-r", "--name-only", "--full-tree", ref, "--", prefix + DOCS)
    return {full[len(prefix) :]: _git("show", f"{ref}:{full}") for full in listed.splitlines()}


def working_tree() -> dict[str, str]:
    return {
        p.relative_to(CONTRACTS).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((CONTRACTS / DOCS).rglob("*"))
        if p.is_file()
    }


def semver(schema: Mapping[str, Any]) -> tuple[int, int, int] | None:
    match = _SEMVER.search(str(schema.get("$comment", "")))
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def strip_annotations(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: strip_annotations(v) for k, v in node.items() if k not in ANNOTATIONS}
    if isinstance(node, list):
        return [strip_annotations(x) for x in node]
    return node


def _examples(tree: Tree) -> dict[str, Any]:
    return {p: json.loads(t) for p, t in tree.items() if p.startswith(f"{DOCS}/examples/") and p.endswith(".json")}


def check(base: Tree, head: Tree) -> list[str]:
    """Ломающие изменения head относительно base; пустой список — совместимо."""
    problems: list[str] = []
    if BODY not in head:
        return [f"{BODY}: файл удалён"] if BODY in base else []
    new = json.loads(head[BODY])
    Draft202012Validator.check_schema(new)
    validator = Draft202012Validator(new)
    if semver(new) is None:
        problems.append(f"{BODY}: в $comment нет «semver X.Y.Z»")
    if BODY in base:
        old = json.loads(base[BODY])
        old_v, new_v = semver(old), semver(new)
        if old["properties"]["version"] != new["properties"]["version"]:
            problems.append(f"{BODY}: сменён мажор тела (version.const) — только новым файлом body.v2.schema.json")
        if old_v and new_v:
            if new_v < old_v:
                problems.append(f"{BODY}: semver уменьшился {old_v} → {new_v}")
            elif strip_annotations(old) != strip_annotations(new) and new_v == old_v:
                problems.append(f"{BODY}: схема изменена, а semver {new_v} прежний — поднимите минор")
            if new_v[0] != old_v[0]:
                problems.append(f"{BODY}: мажор semver сменён в том же файле — только новым файлом")
    for path, body in sorted(_examples(base).items()):
        errors = list(validator.iter_errors(body))
        if errors:
            where = "/".join(str(p) for p in errors[0].absolute_path) or "#"
            problems.append(f"{path} (база) не проходит новую схему: {where}: {errors[0].message[:160]} (сужение)")
    if CATALOG in base and CATALOG in head:
        old_cat, new_cat = yaml.safe_load(base[CATALOG]), yaml.safe_load(head[CATALOG])
        for section in ("variables", "blocks"):
            gone = {v["code"] for v in old_cat[section]} - {v["code"] for v in new_cat[section]}
            problems += [f"{CATALOG}: код {code} удалён или переименован ({section})" for code in sorted(gone)]
        gone_kinds = set(old_cat["kinds"]) - set(new_cat["kinds"])
        problems += [f"{CATALOG}: вид {kind} удалён" for kind in sorted(gone_kinds)]
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
    problems = check(base, working_tree())
    if problems:
        print(f"documents-compat: ломающие изменения относительно {args.base}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"documents-compat: совместимо с {args.base} (примеров базы: {len(_examples(base))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
