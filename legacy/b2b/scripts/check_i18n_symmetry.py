#!/usr/bin/env python3
"""
Verify that ru.json and en.json have identical key sets.

Usage:
    python3 scripts/check_i18n_symmetry.py

Exit codes:
    0 — symmetric
    1 — keys diverge (prints details)
    2 — one of the files is invalid JSON
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RU_PATH = ROOT / 'frontend' / 'src' / 'i18n' / 'locales' / 'ru.json'
EN_PATH = ROOT / 'frontend' / 'src' / 'i18n' / 'locales' / 'en.json'


def flatten(d, path='', out=None):
    if out is None:
        out = set()
    for key, value in d.items():
        full = f'{path}.{key}' if path else key
        if isinstance(value, dict):
            flatten(value, full, out)
        else:
            out.add(full)
    return out


def main() -> int:
    try:
        ru_keys = flatten(json.loads(RU_PATH.read_text(encoding='utf-8')))
        en_keys = flatten(json.loads(EN_PATH.read_text(encoding='utf-8')))
    except json.JSONDecodeError as e:
        print(f'ERROR: invalid JSON — {e}')
        return 2

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

    only_ru = sorted(ru_keys - en_keys)
    only_en = sorted(en_keys - ru_keys)

    # Filter out keys that differ only in pluralization suffixes:
    # if the base key (without suffix) exists in the other language, it's fine.
    ru_bases = strip_plural_keys(ru_keys)
    en_bases = strip_plural_keys(en_keys)

    only_ru = [k for k in only_ru if _PLURAL_SUFFIX_RE.sub('', k) not in en_bases]
    only_en = [k for k in only_en if _PLURAL_SUFFIX_RE.sub('', k) not in ru_bases]

    if not only_ru and not only_en:
        print(f'OK: {len(ru_keys)} RU keys, {len(en_keys)} EN keys, symmetric (pluralization-aware).')
        return 0

    if only_ru:
        print(f'Missing in en.json ({len(only_ru)}):')
        for k in only_ru:
            print(f'  - {k}')
    if only_en:
        print(f'Missing in ru.json ({len(only_en)}):')
        for k in only_en:
            print(f'  - {k}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
