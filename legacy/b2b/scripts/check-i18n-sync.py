#!/usr/bin/env python3
"""
Check that ru.json and en.json have identical key structures.
Runs as a pre-commit hook and in CI (GitHub Actions).

Exit code 0 = sync OK, exit code 1 = mismatch found.
"""

import json
import re
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

    # i18next pluralization suffixes that are language-specific.
    # Russian uses _one/_few/_many/_other; English uses _one/_other.
    # These asymmetric keys are expected and should not be flagged.
    _PLURAL_SUFFIX_RE = re.compile(r'_(?:zero|one|two|few|many|other)$')

    def strip_plural_keys(keys):
        """Return base keys with plural suffixes removed."""
        bases = set()
        for k in keys:
            bases.add(_PLURAL_SUFFIX_RE.sub('', k))
        return bases

    raw_only_ru = ru_keys - en_keys
    raw_only_en = en_keys - ru_keys

    ru_bases = strip_plural_keys(ru_keys)
    en_bases = strip_plural_keys(en_keys)

    only_ru = sorted(k for k in raw_only_ru if _PLURAL_SUFFIX_RE.sub('', k) not in en_bases)
    only_en = sorted(k for k in raw_only_en if _PLURAL_SUFFIX_RE.sub('', k) not in ru_bases)

    ok = True

    if only_ru:
        ok = False
        print(f"\n{len(only_ru)} key(s) in ru.json but MISSING from en.json:")
        for k in only_ru:
            print(f"  - {k}")

    if only_en:
        ok = False
        print(f"\n{len(only_en)} key(s) in en.json but MISSING from ru.json:")
        for k in only_en:
            print(f"  - {k}")

    if ok:
        print(f"i18n sync OK: {len(ru_keys)} keys in ru.json, {len(en_keys)} keys in en.json (pluralization-aware)")
        return 0
    else:
        print(f"\ni18n DESYNC: ru={len(ru_keys)} keys, en={len(en_keys)} keys")
        return 1


if __name__ == "__main__":
    sys.exit(main())
