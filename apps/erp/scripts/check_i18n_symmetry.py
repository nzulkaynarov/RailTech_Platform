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
LOCALES_DIR = ROOT / 'frontend' / 'src' / 'i18n' / 'locales'
# Язык-ИСТОЧНИК: его набор ключей — эталон, с ним сверяются ВСЕ остальные локали.
# Локали не перечислены списком: скрипт обходит каталог, поэтому uz-Latn/uz-Cyrl начнут
# проверяться автоматически, как только появятся файлы (L3, spec-bilingual-ru-en §5).
SOURCE_LOCALE = 'ru'
RU_PATH = LOCALES_DIR / f'{SOURCE_LOCALE}.json'
SRC_DIR = ROOT / 'frontend' / 'src'

_PLURAL_SUFFIX_RE = re.compile(r'_(?:zero|one|two|few|many|other)$')
# Static translation-key calls: t('a.b.c') / t("a.b.c") / i18n.t('a.b.c').
# Template-literal keys (t(`a.${x}`)) are dynamic and intentionally NOT matched.
_T_CALL_RE = re.compile(r"""(?:\bi18n\.t|\bt)\(\s*['"]([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)['"]""")
def load_with_dupes(path):
    """Load JSON, collecting any duplicate key paths (last-wins shadowing)."""
    dupes = []

    def hook(pairs):
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


_CYRILLIC_RE = re.compile(r'[А-Яа-яЁё]')


def _collect_values(node, out, prefix=''):
    """Плоский {ключ: строковое значение} — для проверки самих ТЕКСТОВ, не только ключей."""
    for key, value in node.items():
        full = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _collect_values(value, out, full)
        elif isinstance(value, str):
            out[full] = value


def target_locales():
    """Все локали, кроме языка-источника, в порядке имён файлов."""
    return sorted(
        path.stem for path in LOCALES_DIR.glob('*.json') if path.stem != SOURCE_LOCALE
    )


def main() -> int:
    problems = 0
    try:
        ru_data, ru_dupes = load_with_dupes(RU_PATH)
        targets = {code: load_with_dupes(LOCALES_DIR / f'{code}.json') for code in target_locales()}
    except json.JSONDecodeError as e:
        print(f'ERROR: invalid JSON — {e}')
        return 2
    if not targets:
        print(f'ERROR: no target locales next to {SOURCE_LOCALE}.json')
        return 2

    # 1. Duplicate keys
    if ru_dupes:
        problems = 1
        print(f'DUPLICATE keys in {SOURCE_LOCALE}.json ({len(ru_dupes)}): {sorted(set(ru_dupes))}')
    for code, (_data, dupes) in targets.items():
        if dupes:
            problems = 1
            print(f'DUPLICATE keys in {code}.json ({len(dupes)}): {sorted(set(dupes))}')

    ru_keys, ru_ns = flatten(ru_data)

    def bases(keys):
        return {_PLURAL_SUFFIX_RE.sub('', k) for k in keys}

    ru_bases = bases(ru_keys)

    # Кириллица допустима в подписях самого переключателя языка: они по канону пишутся на
    # своём языке. Для локалей на кириллице (в будущем uz-Cyrl) проверка не применяется —
    # см. ниже `is_latin_locale`.
    CYRILLIC_ALLOWED = {
        'languageSwitcher.switchToRu',
        'languageSwitcher.labelRu',
        'settings.general.langRu',
    }

    for code in sorted(targets):
        data, _dupes = targets[code]
        keys, _ns = flatten(data)
        key_bases = bases(keys)

        # 2. Симметрия с языком-источником (с учётом плюральных форм)
        missing = [k for k in sorted(ru_keys - keys) if _PLURAL_SUFFIX_RE.sub('', k) not in key_bases]
        extra = [k for k in sorted(keys - ru_keys) if _PLURAL_SUFFIX_RE.sub('', k) not in ru_bases]
        if missing:
            problems = 1
            print(f'Missing in {code}.json ({len(missing)}):')
            for k in missing:
                print(f'  - {k}')
        if extra:
            problems = 1
            print(f'Missing in {SOURCE_LOCALE}.json, present in {code}.json ({len(extra)}):')
            for k in extra:
                print(f'  - {k}')

        # 3. Кириллица в ЛАТИНСКОЙ локали = непереведённая строка или русская аббревиатура
        # внутри английской фразы («…your first КП sent», найдено глазами 02-08). Для локали
        # на кириллице (uz-Cyrl) проверка бессмысленна и не выполняется.
        is_latin_locale = 'Cyrl' not in code and code.split('-')[0] not in {'ru', 'uk', 'kk', 'sr'}
        if is_latin_locale:
            values = {}
            _collect_values(data, values)
            cyrillic = sorted(
                (k, v) for k, v in values.items()
                if k not in CYRILLIC_ALLOWED and _CYRILLIC_RE.search(v)
            )
            if cyrillic:
                problems = 1
                print(f'\nCyrillic text in {code}.json ({len(cyrillic)}) — untranslated or a RU abbreviation:')
                for k, v in cyrillic:
                    print(f'  - {k}: {v[:70]}')

    # 4. Used-in-code keys missing from locales (would render raw)
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
        sizes = ', '.join(f'{code}={len(flatten(data)[0])}' for code, (data, _d) in sorted(targets.items()))
        print(f'OK: {SOURCE_LOCALE}={len(ru_keys)} keys, {sizes} — symmetric, no duplicates, '
              f'{len(used)} static t() keys all resolve.')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
