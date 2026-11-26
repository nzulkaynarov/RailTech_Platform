#!/usr/bin/env python3
"""Copy guard: checks user-facing strings against the plain-language standard (ui-standard §13–§14, copy D1–D12).

Two modes::

    # audit: classify an inventory produced by extract.py, write findings.csv
    python3 -I copy_guard.py audit <strings.jsonl> <findings.csv> [--repo <root>]

    # guard (CI): fail when an app gets a finding that is not in its baseline (the baseline only shrinks)
    python3 -I copy_guard.py check <repo_root> --app cabinet --baseline copy-baseline.cabinet.json [--update]

Word lists live next to this file in ``wordlists/*.tsv`` (one class per file):
``regex <TAB> severity H|M|L <TAB> langs (ru,en,uz|*) <TAB> audiences (staff,client,partner,any|*) <TAB> proposal <TAB> note``.
Patterns are case-insensitive; wrap a part in ``(?-i:...)`` for case-sensitive abbreviations.

Classes in code (no word list): uz-old (scripts/uz_new_alphabet.py), mixed (language mix), code (internal keys and
ids shown to users), retelling (long how-it-works copy), untranslated (en/uz equal to ru or in Cyrillic).
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
CYR = re.compile(r"[А-Яа-яЁё]")

CLASS_TITLES = {
    "jargon": "Жаргон и системные слова",
    "audience": "Внутреннее слово клиенту или партнёру (лид, сделка, КП, контакт, платформа)",
    "vendor": "Бренд стороннего сервиса вне Настроек",
    "jobtitle": "Должность вместо действия",
    "promise": "Ложное или расплывчатое обещание",
    "retelling": "Пересказ процесса",
    "gender": "Формы «(а)»",
    "code": "Внутренний код, ключ или id на экране",
    "terms": "Слово не из словаря (разнобой)",
    "honesty": "Статус или действие обещает больше, чем произошло",
    "mixed": "Смешение языков",
    "untranslated": "Нет перевода (en/uz совпадает с ru или по-русски)",
    "uz-old": "Узбекский в старой латинице",
}

# Surfaces whose strings are never shown as copy (search synonyms) are skipped entirely.
SKIP_SURFACES = {"search-terms"}
# Lower priority: Django admin field labels (technical admins only), role catalogue names.
LOW_SURFACES = {"admin-model", "roles"}
# Classes that are allowed where the system is configured (Настройки · Подключения, bus/audit journal, system state).
SETTINGS_OK = {"jargon", "vendor", "mixed"}

LATIN_OK = {
    # formats, units, common loan abbreviations, currencies, Incoterms, document marks
    "pdf", "excel", "xlsx", "docx", "csv", "png", "jpg", "jpeg", "svg", "zip", "word", "e-mail", "email", "wi-fi",
    "qr", "usd", "uzs", "eur", "rub", "cny", "kzt", "exw", "fca", "dap", "ddp", "cpt", "cip", "fob", "cif", "dpu",
    "cfr", "fas", "incoterms", "vat", "telegram", "max", "min", "ok", "esc", "enter", "tab", "ctrl", "shift",
    "iso", "gost", "a4", "mb", "kb", "gb", "ip", "www", "http", "https", "jpeg", "webp", "gif", "heic", "txt",
    "rtf", "odt", "zip", "rar", "xls", "doc", "ppt", "pptx", "android", "ios",
    "markdown",  # a file format the user picks a file of (knowledge base upload)
}

# A language is named in its own language in every locale (the language switcher): not a mixed or untranslated text.
SELF_NAME_KEY = re.compile(r"(^|[:.])languages\.(ru|en|uz)$")


def _load_allow() -> list[tuple[re.Pattern, str, str]]:
    """allow.tsv: key regex, class, reason — findings that are false alarms and are explained, not baselined."""
    out = []
    path = HERE / "allow.tsv"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                key, cls, reason = (line.split("\t") + ["", ""])[:3]  # an optional 4th column names the app (counted by its test)
                if not reason.strip():
                    raise ValueError(f"allow.tsv: a reason is required for {key!r}")
                out.append((re.compile(key), cls, reason))
    return out


ALLOW = _load_allow()


@dataclass(frozen=True)
class Rule:
    cls: str
    regex: re.Pattern[str]
    severity: str
    langs: frozenset[str]
    audiences: frozenset[str]
    proposal: str
    note: str

    def applies(self, lang: str, audience: str) -> bool:
        return ("*" in self.langs or lang in self.langs) and ("*" in self.audiences or audience in self.audiences)


def load_rules(directory: Path = HERE / "wordlists") -> list[Rule]:
    rules: list[Rule] = []
    for f in sorted(directory.glob("*.tsv")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t") + [""] * 6
            rx, sev, langs, auds, proposal, note = parts[:6]
            rules.append(
                Rule(
                    cls=f.stem,
                    regex=re.compile(rx, re.I),
                    severity=sev or "M",
                    langs=frozenset(x.strip() for x in (langs or "*").split(",")),
                    audiences=frozenset(x.strip() for x in (auds or "*").split(",")),
                    proposal=proposal,
                    note=note,
                )
            )
    return rules


def _load_uz(repo: Path | None):
    for cand in ([repo / "scripts/uz_new_alphabet.py"] if repo else []) + [HERE / "uz_new_alphabet.py"]:
        if cand.exists():
            spec = importlib.util.spec_from_file_location("uz_new_alphabet", cand)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader
            sys.modules["uz_new_alphabet"] = mod
            spec.loader.exec_module(mod)
            return mod.convert_uz
    return None


PLACEHOLDER = re.compile(r"(?<![\w/])/[a-z_]+\b|\{\{[^}]*\}\}|\{[^{}]*\}|%\([^)]*\)[sdif]|%[sdif]|\$t\([^)]*\)|<[^>]+>|https?://\S+|[\w.+-]+@[\w-]+(\.[\w-]+)+")
CODE_PLACEHOLDER = re.compile(r"\{\{\s*(\w*(?:_id|Id|ID|uuid|code|slug|key|status|state|kind|error)\w*)\s*\}\}|\{(\w*(?:_id|uuid|slug|_key|status_code|error_code))\}")
SNAKE = re.compile(r"(?<![\w{%$.])[a-z]+_[a-z_]+\b(?![}(])")
CAPS_CODE = re.compile(r"\b[A-Z]{2,}_[A-Z_]{2,}\b")
HASH_ID = re.compile(r"#\s?(\{\{?\w+\}?\}?|\d{2,})")
HTTP_CODE = re.compile(r"(ошибк\w*|error|xato)\s*\(?\s*[45]\d\d\b|\b[45]\d\d\s*(error|ошибк)", re.I)
RETELL_PHRASES = re.compile(
    r"после того,? как|система (сама|автоматически)|на следующем шаге|затем|далее (система|менеджер|бот)|"
    r"это нужно,? чтобы|сначала .* потом", re.I)
LEGAL_SRC = re.compile(r"(partner_contract|offer|policy|privacy|consent|terms_of|legal\.json|/legal/)", re.I)
UI_SURFACES = {"ui", "hardcoded-ui", "bot", "notification", "error", "api-text", "status"}


@dataclass
class Finding:
    app: str
    surface: str
    audience: str
    lang: str
    source: str
    key: str
    cls: str
    severity: str
    match: str
    text: str
    proposal: str
    note: str


def _norm_sev(sev: str, row: dict) -> str:
    if row["surface"] in LOW_SURFACES:
        return "L"
    return sev


def check_row(row: dict, rules: list[Rule], convert_uz, ru_by_key: dict | None = None) -> list[Finding]:
    if row["surface"] in SKIP_SURFACES:
        return []
    out: list[Finding] = []
    text, lang, aud = row["text"], row["lang"], row["audience"]
    plain = PLACEHOLDER.sub(" ", text)

    legal = bool(LEGAL_SRC.search(row["source"]))

    def add(cls, sev, match, proposal, note=""):
        if any(rx.fullmatch(row["key"]) and c == cls for rx, c, _ in ALLOW):
            return
        if cls in ("mixed", "untranslated") and SELF_NAME_KEY.search(row["key"]):
            return
        if row.get("ctx") == "settings" and cls == "code":
            sev = "L"
        if legal:
            sev, note = "L", "D10: юридический текст — не править, передать держателю зоны «Право»"
        out.append(Finding(row["app"], row["surface"], aud, lang, row["source"], row["key"], cls,
                           _norm_sev(sev, row), match, text, proposal, note))

    seen_cls: set[str] = set()
    for r in rules:
        if not r.applies(lang, aud):
            continue
        if r.cls in SETTINGS_OK and row.get("ctx") == "settings":
            continue
        if r.cls == "jobtitle" and (row.get("ctx") == "roles" or row["surface"] == "roles" or "/changelog/" in row["source"]):
            continue
        m = r.regex.search(plain)
        if not m:
            continue
        key = (r.cls, m.group(0).lower())
        if key in seen_cls:
            continue
        seen_cls.add(key)
        sev = r.severity
        if aud in ("client", "partner") and sev == "M" and r.cls in {"jargon", "promise", "code", "vendor"}:
            sev = "H"
        add(r.cls, sev, m.group(0), r.proposal, r.note)

    # code: internal keys and ids shown to users
    m = CODE_PLACEHOLDER.search(text)
    if m:
        add("code", "M", m.group(0), "показать название или номер документа, не код", "D5")
    for rx, sev in ((SNAKE, "H"), (CAPS_CODE, "H"), (HTTP_CODE, "M")):
        m = rx.search(plain)
        if m and not (rx is SNAKE and row["surface"] in {"help"}):
            add("code", sev, m.group(0), "(убрать код; назвать причину словами)", "ui-standard §14 п.4")
            break
    m = HASH_ID.search(text)
    if m and aud in ("client", "partner", "any"):
        add("code", "H", m.group(0), "номер документа (ЗВ-…, ПР-…), не внутренний id", "D5")

    # mixed language (system names are fine where the system is configured)
    if row.get("ctx") == "settings":
        pass
    elif lang == "ru":
        words = [w for w in re.findall(r"(?<![\w-])[A-Za-z][A-Za-z-]{2,}(?![\w-])", plain)]
        bad = [w for w in words if w.lower() not in LATIN_OK and not re.fullmatch(r"[A-Z]{2,}", w)]
        if bad:
            add("mixed", "M", " ".join(dict.fromkeys(bad))[:60], "по-русски", "")
    elif lang in ("en", "uz"):
        cyr = re.findall(r"[А-Яа-яЁё][А-Яа-яЁё\s-]{2,}", re.sub(r"«[^»]*»|\"[^\"]*\"", " ", plain))
        # product designations in Cyrillic (РУ1Ш-957-Г) are data
        cyr = [c for c in cyr if not re.search(r"\d", c) and len(c.strip()) > 2]
        if cyr:
            ru = (ru_by_key or {}).get((row["app"], row["key"])) if ru_by_key else None
            if ru is not None and ru.strip() == text.strip():
                add("untranslated", "M", cyr[0][:40], f"перевести на {lang}", "")
            else:
                add("mixed", "M", cyr[0][:40], f"перевести на {lang}", "")
        elif ru_by_key is not None and lang in ("en", "uz"):
            ru = ru_by_key.get((row["app"], row["key"]))
            if ru and len(ru) > 3 and ru == text and CYR.search(ru):
                add("untranslated", "M", text[:40], f"перевести на {lang}", "")

    # uz old alphabet
    if lang == "uz" and convert_uz is not None:
        new = convert_uz(text)
        if new != text:
            add("uz-old", "M", "oʻ/gʻ/sh/ch", new, "scripts/uz_new_alphabet.py")

    # process retelling
    if lang == "ru" and row["surface"] in UI_SURFACES and row["surface"] not in LOW_SURFACES:
        k = row["key"].lower()
        long_ok = any(s in k for s in ("article", "legal", "body", "help", "faq", "kb.", "template", "consent", "offer"))
        sentences = len([s for s in re.split(r"(?<=[.!?])\s+", plain.strip()) if len(s) > 3])
        if not long_ok and (len(plain) > 220 or (sentences >= 3 and len(plain) > 140)):
            add("retelling", "M" if aud == "staff" else "H", f"{len(plain)} зн., {sentences} предл.",
                "сократить до действия и исхода; объяснение — в справку", "minimal-interface-copy")
        elif RETELL_PHRASES.search(plain):
            add("retelling", "L", RETELL_PHRASES.search(plain).group(0), "убрать пересказ процесса", "minimal-interface-copy")
    return out


def audit(rows: list[dict], repo: Path | None) -> list[Finding]:
    rules = load_rules()
    conv = _load_uz(repo)
    ru_by_key = {(r["app"], r["key"]): r["text"] for r in rows if r["lang"] == "ru" and r["surface"] == "ui"}
    findings: list[Finding] = []
    for r in rows:
        findings.extend(check_row(r, rules, conv, ru_by_key if r["surface"] == "ui" else None))
    return findings


FIELDS = ["app", "surface", "audience", "lang", "source", "key", "cls", "severity", "match", "text", "proposal", "note"]


def write_csv(findings: list[Finding], path: Path, curated: dict | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["app", "surface", "audience", "lang", "source", "key", "problem_class", "class_title", "severity",
                    "match", "current_text", "proposed_text", "note"])
        for f in findings:
            prop = f.proposal
            if curated and (f.key, f.lang) in curated:
                prop = curated[(f.key, f.lang)]
            w.writerow([f.app, f.surface, f.audience, f.lang, f.source, f.key, f.cls, CLASS_TITLES.get(f.cls, f.cls),
                        f.severity, f.match, f.text, prop, f.note])


# ── guard mode (CI) ───────────────────────────────────────────────────────────────────────────────────

def _fingerprint(f: Finding) -> str:
    src = re.sub(r":\d+( \(\w+ po\))?$", "", f.source)  # line numbers move; key + text + class are stable
    return f"{f.severity}|{f.app}|{src}|{f.key}|{f.lang}|{f.cls}|{f.match.lower()}"


def guard(repo: Path, app: str, baseline: Path, update: bool, show: bool = False) -> int:
    spec = importlib.util.spec_from_file_location("copy_extract", HERE / "extract.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    rows: list[dict] = []
    for gen in (mod.extract_json, mod.extract_ts, mod.extract_py, mod.extract_templates, mod.extract_help):
        rows.extend(r for r in gen(repo) if r["app"] == app or (app == "platform" and r["app"] == "platform-bff"))
    rows.extend(mod.extract_po_pairs(repo, rows))
    findings = audit(rows, repo)
    if show:
        for f in findings:
            if f.severity in ("H", "M"):
                print(f.severity, f.lang, f.source, f.key, f.cls, "|", f.match, "|", f.text[:110].replace("\n", " "))
    found = sorted({_fingerprint(f) for f in findings})
    if update or not baseline.exists():
        baseline.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"baseline written: {len(found)} findings")
        return 0
    known = set(json.loads(baseline.read_text(encoding="utf-8")))
    new = [x for x in found if x not in known]
    gone = [x for x in known if x not in set(found)]
    for x in new:
        print("NEW  ", x)
    if gone:
        print(f"{len(gone)} baseline entries are fixed — remove them (run with --update): the list only shrinks")
    print(f"{app}: {len(found)} findings, {len(new)} new, {len(gone)} fixed")
    return 1 if new or gone else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("strings")
    a.add_argument("out")
    a.add_argument("--repo", type=Path)
    a.add_argument("--curated", type=Path)
    g = sub.add_parser("check")
    g.add_argument("repo", type=Path)
    g.add_argument("--app", required=True)
    g.add_argument("--baseline", type=Path, required=True)
    g.add_argument("--update", action="store_true")
    g.add_argument("--show", action="store_true", help="print H and M findings with their text")
    args = p.parse_args(argv)
    if args.cmd == "audit":
        rows = [json.loads(x) for x in Path(args.strings).read_text(encoding="utf-8").splitlines()]
        findings = audit(rows, args.repo)
        curated = None
        if args.curated and args.curated.exists():
            curated = {}
            with args.curated.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    curated[(r["key"], r["lang"])] = r["proposed"]
        write_csv(findings, Path(args.out), curated)
        c = Counter((f.cls, f.severity) for f in findings)
        for k, v in sorted(c.items()):
            print(*k, v, sep="\t")
        print("total", len(findings), sep="\t")
        return 0
    return guard(args.repo, args.app, args.baseline, args.update, args.show)


if __name__ == "__main__":
    raise SystemExit(main())
