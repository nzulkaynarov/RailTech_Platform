#!/usr/bin/env python3
"""
Check that ru.json and en.json have identical key structures.
Runs as a pre-commit hook and in CI (GitHub Actions).

Exit code 0 = sync OK, exit code 1 = mismatch found.
"""

import json
import sys
from pathlib import Path


def collect_keys(obj: dict, prefix: str = "") -> set[str]:
    """Recursively collect all leaf key paths from a nested dict."""
    keys = set()
    for k, v in obj.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(collect_keys(v, path))
        else:
            keys.add(path)
    return keys


def main() -> int:
    locales_dir = Path(__file__).resolve().parent.parent / "frontend" / "src" / "i18n" / "locales"
    ru_path = locales_dir / "ru.json"
    en_path = locales_dir / "en.json"

    if not ru_path.exists():
        print(f"ERROR: {ru_path} not found")
        return 1
    if not en_path.exists():
        print(f"ERROR: {en_path} not found")
        return 1

    with open(ru_path, encoding="utf-8") as f:
        ru = json.load(f)
    with open(en_path, encoding="utf-8") as f:
        en = json.load(f)

    ru_keys = collect_keys(ru)
    en_keys = collect_keys(en)

    only_ru = ru_keys - en_keys
    only_en = en_keys - ru_keys

    ok = True

    if only_ru:
        ok = False
        print(f"\n{len(only_ru)} key(s) in ru.json but MISSING from en.json:")
        for k in sorted(only_ru):
            print(f"  - {k}")

    if only_en:
        ok = False
        print(f"\n{len(only_en)} key(s) in en.json but MISSING from ru.json:")
        for k in sorted(only_en):
            print(f"  - {k}")

    if ok:
        print(f"i18n sync OK: {len(ru_keys)} keys in ru.json, {len(en_keys)} keys in en.json")
        return 0
    else:
        print(f"\ni18n DESYNC: ru={len(ru_keys)} keys, en={len(en_keys)} keys")
        return 1


if __name__ == "__main__":
    sys.exit(main())
