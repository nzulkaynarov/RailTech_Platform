#!/usr/bin/env python3
"""
i18n integrity check for ru.json / en.json and their usage in code.

Three checks (any failure → non-zero exit, details printed):
  1. Duplicate keys within a single locale file (JSON silently keeps the last,
     which SHADOWS earlier keys — this is how the onboarding banner once rendered
     raw keys: two "onboarding" objects, the second hid the first).
  2. Key-set symmetry between ru.json and en.json (pluralization-aware).
  3. Static t('...') / i18n.t('...') keys used in frontend/src that are MISSING
     from the locales (would render the raw key on screen).

Usage:
    python3 scripts/check_i18n_symmetry.py
Exit codes: 0 ok · 1 problems found · 2 invalid JSON
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RU_PATH = ROOT / 'frontend' / 'src' / 'i18n' / 'locales' / 'ru.json'
EN_PATH = ROOT / 'frontend' / 'src' / 'i18n' / 'locales' / 'en.json'
SRC_DIR = ROOT / 'frontend' / 'src'

_PLURAL_SUFFIX_RE = re.compile(r'_(?:zero|one|two|few|many|other)$')
# Static translation-key calls: t('a.b.c') / t("a.b.c") / i18n.t('a.b.c').
# Template-literal keys (t(`a.${x}`)) are dynamic and intentionally NOT matched.
_T_CALL_RE = re.compile(r"""(?:\bi18n\.t|\bt)\(\s*['"]([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)['"]""")
# Calls that pass an explicit defaultValue are intentional fallbacks — exclude.
_T_DEFAULT_RE = re.compile(r"""(?:\bi18n\.t|\bt)\(\s*['"][^'"]+['"]\s*,\s*\{[^}]*defaultValue""")


def load_with_dupes(path):
    """Load JSON, collecting any duplicate key paths (last-wins shadowing)."""
    dupes = []

    def hook(pairs, _path=['']):
        seen = {}
        out = {}
        for k, v in pairs:
            if k in seen:
                dupes.append(k)
            seen[k] = True
            out[k] = v
        return out

    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=hook)
    return data, dupes


def flatten(d, path='', out=None, namespaces=None):
    if out is None:
        out = set()
    if namespaces is None:
        namespaces = set()
    for key, value in d.items():
        full = f'{path}.{key}' if path else key
        if isinstance(value, dict):
            namespaces.add(full)
            flatten(value, full, out, namespaces)
        else:
            out.add(full)
    return out, namespaces


def collect_used_keys():
    used = {}  # key -> first "file:line"
    for f in list(SRC_DIR.rglob('*.ts')) + list(SRC_DIR.rglob('*.tsx')):
        try:
            text = f.read_text(encoding='utf-8')
        except Exception:
            continue
        for m in _T_CALL_RE.finditer(text):
            # Skip calls that pass an explicit defaultValue (intentional fallback),
            # checking a window after the key since the call may span lines.
            window = text[m.start():m.start() + 220]
            if 'defaultValue' in window:
                continue
            key = m.group(1)
            line_no = text.count('\n', 0, m.start()) + 1
            used.setdefault(key, f'{f.relative_to(ROOT)}:{line_no}')
    return used


def main() -> int:
    problems = 0
    try:
        ru_data, ru_dupes = load_with_dupes(RU_PATH)
        en_data, en_dupes = load_with_dupes(EN_PATH)
    except json.JSONDecodeError as e:
        print(f'ERROR: invalid JSON — {e}')
        return 2

    # 1. Duplicate keys
    if ru_dupes or en_dupes:
        problems = 1
        if ru_dupes:
            print(f'DUPLICATE keys in ru.json ({len(ru_dupes)}): {sorted(set(ru_dupes))}')
        if en_dupes:
            print(f'DUPLICATE keys in en.json ({len(en_dupes)}): {sorted(set(en_dupes))}')

    ru_keys, ru_ns = flatten(ru_data)
    en_keys, _ = flatten(en_data)

    # 2. Symmetry (pluralization-aware)
    def bases(keys):
        return {_PLURAL_SUFFIX_RE.sub('', k) for k in keys}
    en_bases, ru_bases = bases(en_keys), bases(ru_keys)
    only_ru = [k for k in sorted(ru_keys - en_keys) if _PLURAL_SUFFIX_RE.sub('', k) not in en_bases]
    only_en = [k for k in sorted(en_keys - ru_keys) if _PLURAL_SUFFIX_RE.sub('', k) not in ru_bases]
    if only_ru:
        problems = 1
        print(f'Missing in en.json ({len(only_ru)}):')
        for k in only_ru:
            print(f'  - {k}')
    if only_en:
        problems = 1
        print(f'Missing in ru.json ({len(only_en)}):')
        for k in only_en:
            print(f'  - {k}')

    # 3. Used-in-code keys missing from locales (would render raw)
    used = collect_used_keys()
    valid = ru_keys | ru_ns  # leaf keys + namespace prefixes
    _PLURALS = ('_zero', '_one', '_two', '_few', '_many', '_other')

    def resolves(k):
        if k in valid:
            return True
        # count-based call: t('x', {count}) resolves via x_one/x_few/... variants
        if any((k + suf) in ru_keys for suf in _PLURALS):
            return True
        # used as a namespace prefix of an existing leaf
        return any(leaf.startswith(k + '.') for leaf in ru_keys)

    missing = sorted(k for k in used if not resolves(k))
    if missing:
        problems = 1
        print(f'\nUsed in code but MISSING from locales ({len(missing)}) — these render as raw keys:')
        for k in missing:
            print(f'  - {k}   (e.g. {used[k]})')

    if not problems:
        print(f'OK: {len(ru_keys)} RU keys, {len(en_keys)} EN keys — symmetric, no duplicates, '
              f'{len(used)} static t() keys all resolve.')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
