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

    only_ru = sorted(ru_keys - en_keys)
    only_en = sorted(en_keys - ru_keys)

    if not only_ru and not only_en:
        print(f'OK: {len(ru_keys)} keys, symmetric.')
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
