#!/usr/bin/env python3
"""Inventory of user-facing strings across the RailTech Platform monorepo.

Usage::

    python3 -I extract.py <repo_root> <out.jsonl>

Every row: {app, surface, audience, source, key, lang, text, ctx}
  app       platform | platform-bff | cabinet | erp | crm | eds | help
  surface   ui | hardcoded-ui | email | pdf | bot | notification | status | error | help | letter | api-text
  audience  staff | client | partner | any
  source    repo-relative path:line
  key       i18n key / python qualname-ish / template name
  ctx       "settings" when the string lives where system and vendor names are allowed
            (connections, bus journal, audit, system state), else ""

Read-only: the script never writes into the repo.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

CYR = re.compile(r"[А-Яа-яЁё]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")

SKIP_DIR_PARTS = {
    "tests", "test", "__tests__", "migrations", "alembic", "e2e", "mocks", "fixtures", "seeds", "evals",
    "prompts", "node_modules", "dist", "generated", "dev", "stories", "management", "scripts", "cli",
}
SETTINGS_HINT = re.compile(
    r"(^|[._/-])(settings|setup|integrations?|connections?|channels?|bus|audit|system_?status|external_|"
    r"providers?|mail_?connect|admin-integrations|admin-bus|admin-audit|admin-mail)",
    re.I,
)


def row(app, surface, audience, source, key, lang, text, ctx=""):
    return {
        "app": app, "surface": surface, "audience": audience, "source": source, "key": key,
        "lang": lang, "text": text, "ctx": ctx,
    }


# ── JSON catalogs ─────────────────────────────────────────────────────────────────────────────────────

def flat(d, p=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from flat(v, f"{p}.{k}" if p else k)
    elif isinstance(d, list):
        for i, x in enumerate(d):
            yield from flat(x, f"{p}[{i}]")
    elif isinstance(d, str):
        yield p, d


def key_lines(path: Path) -> dict[str, int]:
    """Best-effort line of each leaf key (by last path segment, in order)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: dict[str, int] = {}
    data = json.loads("\n".join(lines))
    keys = [k for k, _ in flat(data)]
    li = 0
    for k in keys:
        leaf = re.sub(r"\[\d+\]$", "", k).rsplit(".", 1)[-1]
        needle = f'"{leaf}"'
        j = li
        while j < len(lines) and needle not in lines[j]:
            j += 1
        if j < len(lines):
            out[k] = j + 1
            li = j
        else:
            out[k] = li + 1
    return out


def cabinet_audience(key: str) -> str:
    k = key.lower()
    if any(s in k for s in ("partner", "supplier", "seller", "rfq", "pricerequest", "price_request", "catalogitems",
                            "myproducts", "assortment")):
        return "partner"
    return "client"


def extract_json(root: Path) -> Iterator[dict]:
    for lang in ("ru", "en", "uz"):
        for f in sorted((root / "apps/platform/web/src/shared/i18n" / lang).glob("*.json")):
            rel = f.relative_to(root).as_posix()
            lines = key_lines(f)
            ns = f.stem
            for k, v in flat(json.loads(f.read_text(encoding="utf-8"))):
                ctx = "settings" if ns in {"integrations", "bus", "audit"} or SETTINGS_HINT.search(k) else ""
                yield row("platform", "ui", "staff", f"{rel}:{lines.get(k, 1)}", f"{ns}:{k}", lang, v, ctx)
        f = root / "apps/cabinet/src/i18n/locales" / f"{lang}.json"
        rel = f.relative_to(root).as_posix()
        lines = key_lines(f)
        for k, v in flat(json.loads(f.read_text(encoding="utf-8"))):
            yield row("cabinet", "ui", cabinet_audience(k), f"{rel}:{lines.get(k, 1)}", k, lang, v)


# ── TS / TSX hardcoded literals ───────────────────────────────────────────────────────────────────────

TS_STR = re.compile(r"""(?P<prop>\b(?:ru|en|uz)\s*:\s*)?(?P<q>['"`])(?P<body>(?:\\.|(?!(?P=q)).)*?)(?P=q)""", re.S)
JSX_TEXT = re.compile(r">([^<>{}]*[А-Яа-яЁё][^<>{}]*)<")


# Files whose strings are developer diagnostics (never shown to a user).
DEV_ONLY_FILES = {"apps/cabinet/src/telegram/theme.ts"}


def extract_ts(root: Path) -> Iterator[dict]:
    for base, app in (("apps/platform/web/src", "platform"), ("apps/cabinet/src", "cabinet")):
        for f in sorted((root / base).rglob("*.ts*")):
            rel = f.relative_to(root).as_posix()
            parts = set(f.relative_to(root / base).parts[:-1])
            if parts & SKIP_DIR_PARTS or "i18n" in parts or re.search(r"\.(test|spec|stories)\.tsx?$", f.name):
                continue
            if rel in DEV_ONLY_FILES:
                continue
            src = f.read_text(encoding="utf-8")
            # strip comments (keep offsets)
            stripped = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), src, flags=re.S)
            stripped = re.sub(r"(?<![:'\"`\\])//[^\n]*", lambda m: " " * len(m.group()), stripped)
            # console output is for developers, not users
            stripped = re.sub(r"console\.\w+\((?:[^()]|\([^()]*\))*\)", lambda m: re.sub(r"[^\n]", " ", m.group()), stripped)
            audience = "staff" if app == "platform" else ("partner" if re.search(r"partner|supplier|seller", rel, re.I) else "client")
            surface = "help" if "helpArticles" in f.name else "hardcoded-ui"
            if "rbac" in f.name:
                surface = "roles"
            if f.name == "settingsRegistry.ts":
                surface = "search-terms"
            seen = set()
            for m in TS_STR.finditer(stripped):
                body = m.group("body")
                prop = (m.group("prop") or "").strip().rstrip(":").strip()
                if not CYR.search(body) and prop not in ("en", "uz"):
                    continue
                if prop in ("en", "uz") and not LATIN_WORD.search(body):
                    continue
                if re.fullmatch(r"[\w./@-]+", body) and not CYR.search(body):
                    continue
                line = stripped.count("\n", 0, m.start()) + 1
                lang = prop or ("ru" if CYR.search(body) else "en")
                seen.add(m.span())
                yield row(app, surface, audience, f"{rel}:{line}", f"{f.name}:{line}", lang, body.replace("\\n", "\n"))
            for m in JSX_TEXT.finditer(stripped):
                txt = m.group(1).strip()
                if txt:
                    line = stripped.count("\n", 0, m.start()) + 1
                    yield row(app, "hardcoded-ui", audience, f"{rel}:{line}", f"{f.name}:{line}", "ru", txt)


# ── Python ────────────────────────────────────────────────────────────────────────────────────────────

LOG_NAMES = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "msg"}
SKIP_KW = {"description", "summary", "help_text", "examples", "example", "pattern", "alias", "db_comment"}
SKIP_FUNCS = {"compile", "match", "search", "fullmatch", "sub", "findall", "finditer", "split"}


def _fstring_text(node: ast.JoinedStr) -> str:
    out = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            out.append(v.value)
        else:
            try:
                out.append("{" + ast.unparse(v.value if isinstance(v, ast.FormattedValue) else v) + "}")
            except Exception:  # noqa: BLE001
                out.append("{…}")
    return "".join(out)


def py_surface(rel: str, app: str) -> tuple[str, str, str]:
    """(surface, audience, ctx) for a python file."""
    r = rel.lower()
    ctx = "settings" if SETTINGS_HINT.search(r) or re.search(
        r"crm_url|telegram_webhook|erp_access|bot/supervisor|console_mount|cbu_banks|erp_connector|alerts\.py|mail_bus|mail_out", r) else ""
    if app == "crm":
        if "/bot/" in r or "client_texts" in r or "settings_client" in r or "schemas/settings.py" in r:
            return "bot", "client", ctx
        if "mail_types" in r or "inbound_mail" in r:
            return "api-text", "staff", ctx
        if "mail" in r and ("mail_types" in r or "services/mail" in r or "portal_invites" in r):
            return "email", "client", ctx
        if "staff_" in r or "channel_texts" in r or "notif" in r or "telegram_groups" in r:
            return "notification", "staff", ctx
        if "errors" in r:
            return "error", "staff", ctx
        return "api-text", "staff", ctx
    if app == "erp":
        if "/admin/" in r or r.endswith("admin.py") or "/resources.py" in r:
            return "admin-model", "staff", ctx
        if "/portal/desk/" in r:
            return "api-text", "staff", ctx
        if "/models" in r or "/models_" in r or r.endswith("models.py") or "choices" in r or "constants" in r:
            return "status", "any", ctx
        if re.search(r"rt_documents|document_blocks|document_wording|documents/preview|documents/sample|money_words", r):
            return "pdf", "client", ctx
        if "/portal/" in r:
            return "api-text", ("partner" if "partner" in r else "client"), ctx
        if "/notifications/" in r:
            return "notification", "any", ctx
        return "api-text", "staff", ctx
    if app == "eds":
        if "letter" in r:
            return "letter", "staff", ctx
        if "notice" in r or "notif" in r:
            return "notification", "staff", ctx
        if "errors" in r:
            return "error", "staff", ctx
        return "api-text", "staff", ctx
    if app == "platform-bff":
        if "/feeds/" in r:
            return "notification", "staff", ctx
        if "errors" in r:
            return "error", "staff", ctx
        return "api-text", "staff", ctx
    return "api-text", "staff", ctx


class PyVisitor(ast.NodeVisitor):
    def __init__(self, rel, app):
        self.rel, self.app = rel, app
        self.rows: list[dict] = []
        self.skip: set[int] = set()
        self.lang_ctx: dict[int, str] = {}
        self.key_ctx: dict[int, str] = {}
        self.stack: list[str] = []

    def _mark_skip(self, node):
        for n in ast.walk(node):
            self.skip.add(id(n))

    def visit_FunctionDef(self, node):
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            self._mark_skip(node.body[0])
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            self._mark_skip(node.body[0])
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Module(self, node):
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            self._mark_skip(node.body[0])
        self.generic_visit(node)

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            self._mark_skip(node)  # bare string statements (attribute docstrings)
        self.generic_visit(node)

    def visit_Call(self, node):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
        owner = ""
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            owner = fn.value.id
        if (name in LOG_NAMES and owner in {"log", "logger", "logging", "_log", "LOG", "self"}) or \
                (name in SKIP_FUNCS and owner in {"re", "regex"}):
            self._mark_skip(node)
        for kw in node.keywords:
            if kw.arg in SKIP_KW:
                self._mark_skip(kw.value)
        self.generic_visit(node)

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and v is not None:
                for n in ast.walk(v):
                    if k.value in ("ru", "en", "uz"):
                        self.lang_ctx.setdefault(id(n), k.value)
                    self.key_ctx.setdefault(id(n), k.value)
        self.generic_visit(node)

    def visit_Assign(self, node):
        tgt = node.targets[0]
        nm = tgt.id if isinstance(tgt, ast.Name) else (tgt.attr if isinstance(tgt, ast.Attribute) else "")
        if nm:
            for n in ast.walk(node.value):
                self.key_ctx.setdefault(id(n), nm)
            if re.search(r"(PATTERN|_RE$|REGEX|KEYWORDS|STOP_?WORDS|MARKERS|HINTS_RE|_TERMS$|_WORDS$|SYNONYMS|ALIASES)", nm, re.I):
                self._mark_skip(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None and isinstance(node.target, ast.Name):
            for n in ast.walk(node.value):
                self.key_ctx.setdefault(id(n), node.target.id)
        self.generic_visit(node)

    def _emit(self, node, text):
        if id(node) in self.skip:
            return
        lang = self.lang_ctx.get(id(node))
        if lang is None:
            if not CYR.search(text):
                return
            lang = "ru"
        elif lang in ("en", "uz") and not LATIN_WORD.search(text):
            return
        if not text.strip() or re.fullmatch(r"[\w.:/@%{}\-]+", text) and not CYR.search(text):
            return
        surface, audience, ctx = py_surface(self.rel, self.app)
        key = ".".join(self.stack + [self.key_ctx.get(id(node), "")]).strip(".") or "-"
        if re.search(r"(stop_words|_terms|keywords|synonyms|aliases)$", key, re.I):
            return
        if re.search(r"\.(erp_staff_|erp_note_|staff_)", key):
            surface, audience = "notification", "staff"
        if self.app == "erp" and surface == "status" and not re.search(r"(Status|Choices|Code|Kind|Stage|Type|State)\b", key):
            surface, audience = "admin-model", "staff"
        if re.search(r"(platform_roles|rbac)", self.rel):
            ctx = "roles"
        self.rows.append(row(self.app, surface, audience, f"{self.rel}:{node.lineno}", key, lang, text, ctx))

    def visit_JoinedStr(self, node):
        self._emit(node, _fstring_text(node))
        for v in node.values:
            if isinstance(v, ast.Constant):
                self.skip.add(id(v))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self._emit(node, node.value)


PY_BASES = (
    ("apps/crm/backend/app", "crm"),
    ("apps/eds/app", "eds"),
    ("apps/platform/bff/app", "platform-bff"),
    ("apps/erp/backend", "erp"),
)
PY_SKIP_FILE = re.compile(r"(/test_|/__main__\.py$|/openapi\.py$|_test\.py$|conftest|settings\.py$(?<!schemas/settings\.py)|_generated\.py$|"
                          r"prompt|/ai/|/agents/|/llm|pii\.py$|countries|/mcp/)")


def extract_py(root: Path) -> Iterator[dict]:
    for base, app in PY_BASES:
        for f in sorted((root / base).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            parts = set(f.relative_to(root / base).parts[:-1])
            if parts & SKIP_DIR_PARTS:
                continue
            if PY_SKIP_FILE.search("/" + rel) and not rel.endswith("schemas/settings.py"):
                continue
            if app == "erp" and rel.startswith("apps/erp/backend/config/"):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            v = PyVisitor(rel, app)
            v.visit(tree)
            yield from v.rows


# ── ERP / CRM templates ───────────────────────────────────────────────────────────────────────────────

TRANS = re.compile(r"""\{%\s*(?:translate|trans)\s+(['"])(.*?)\1.*?%\}""", re.S)
BLOCKTRANS = re.compile(r"\{%\s*blocktrans(?:late)?\b[^%]*%\}(.*?)\{%\s*endblocktrans(?:late)?\s*%\}", re.S)


def template_surface(rel: str) -> tuple[str, str]:
    r = rel.lower()
    name = r.rsplit("/", 1)[-1]
    if "/emails/" in r or "mail" in r:
        aud = "partner" if re.search(r"rfq|price_request|supplier|partner|seller", name) else "client"
        if re.search(r"reset_password|setup_password|account_created", name):
            aud = "any"
        return "email", aud
    if "/crm/templates/crm" in r or "document" in r:
        return "pdf", "client"
    if "/admin/" in r:
        return "admin", "staff"
    return "ui", "client"


def extract_templates(root: Path) -> Iterator[dict]:
    for base, app in (("apps/erp/backend", "erp"), ("apps/crm/backend", "crm"), ("apps/eds", "eds")):
        for f in sorted((root / base).rglob("*")):
            if not f.is_file() or "templates" not in f.parts or f.suffix not in {".html", ".txt", ".md", ".j2", ".jinja"}:
                continue
            rel = f.relative_to(root).as_posix()
            if set(f.relative_to(root / base).parts) & {"tests", "node_modules"}:
                continue
            surface, aud = template_surface(rel)
            if surface == "admin":
                continue
            if app == "crm":
                aud = "staff"
            mlang = re.search(r"\.(ru|en|uz)\.\w+$", f.name)
            flang = mlang.group(1) if mlang else "ru"
            src = f.read_text(encoding="utf-8")
            spans = []
            for m in list(TRANS.finditer(src)) + list(BLOCKTRANS.finditer(src)):
                txt = m.group(2) if m.re is TRANS else m.group(1)
                line = src.count("\n", 0, m.start()) + 1
                spans.append(m.span())
                yield row(app, surface, aud, f"{rel}:{line}", f.name, "ru", re.sub(r"\s+", " ", txt).strip())
            # raw text outside template tags
            masked = src
            for s, e in spans:
                masked = masked[:s] + " " * (e - s) + masked[e:]
            masked = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group()), masked, flags=re.S)
            masked = re.sub(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", lambda m: " " * len(m.group()), masked, flags=re.S)
            masked = re.sub(r"<style.*?</style>", lambda m: re.sub(r"[^\n]", " ", m.group()), masked, flags=re.S)
            masked = re.sub(r"<[^>]+>", lambda m: re.sub(r"[^\n]", " ", m.group()), masked, flags=re.S)
            for i, line in enumerate(masked.splitlines(), 1):
                t = line.strip()
                if (flang == "ru" and CYR.search(t)) or (flang != "ru" and LATIN_WORD.search(t) and not t.startswith("$")):
                    yield row(app, surface, aud, f"{rel}:{i}", f.name, flang, t)


# ── ERP .po (translations of ru msgids) ───────────────────────────────────────────────────────────────

def parse_po(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = {"msgid": [], "msgstr": []}
    field = None

    def flush():
        mid = "".join(cur["msgid"])
        ms = "".join(cur["msgstr"])
        if mid and ms:
            out[mid] = ms

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            flush()
            cur = {"msgid": [], "msgstr": []}
            field = "msgid"
            line = line[6:]
        elif line.startswith("msgstr"):
            field = "msgstr"
            line = line.split(" ", 1)[1] if " " in line else '""'
        elif line.startswith("msgid_plural") or line.startswith("#"):
            field = None if line.startswith("#") else field
            continue
        if field and line.startswith('"'):
            cur[field].append(json.loads(line))
    flush()
    return out


def extract_po_pairs(root: Path, rows: list[dict]) -> Iterator[dict]:
    """Emit en/uz rows for ERP ru strings that have a translation in django.po."""
    for lang in ("en", "uz"):
        po = root / f"apps/erp/backend/locale/{lang}/LC_MESSAGES/django.po"
        if not po.exists():
            continue
        tr = parse_po(po)
        for r in rows:
            if r["app"] == "erp" and r["lang"] == "ru" and r["text"] in tr:
                yield {**r, "lang": lang, "text": tr[r["text"]], "source": r["source"] + f" ({lang} po)"}


# ── staff help (docs/kb/help) ─────────────────────────────────────────────────────────────────────────

def extract_help(root: Path) -> Iterator[dict]:
    for f in sorted((root / "docs/kb/help").rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        lines = f.read_text(encoding="utf-8").splitlines()
        in_fm = in_code = False
        for i, line in enumerate(lines, 1):
            if i == 1 and line.strip() == "---":
                in_fm = True
                continue
            if in_fm:
                if line.strip() == "---":
                    in_fm = False
                elif line.startswith("title:"):
                    yield row("help", "help", "staff", f"{rel}:{i}", f.stem + ":title", "ru", line[6:].strip())
                continue
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not CYR.search(line):
                continue
            ctx = "settings" if SETTINGS_HINT.search(f.stem) else ""
            yield row("help", "help", "staff", f"{rel}:{i}", f.stem, "ru", line.strip(" -#>*"), ctx)


def main() -> int:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows: list[dict] = []
    for gen in (extract_json, extract_ts, extract_py, extract_templates, extract_help):
        rows.extend(gen(root))
    rows.extend(list(extract_po_pairs(root, rows)))
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    c = Counter((r["app"], r["surface"], r["lang"]) for r in rows)
    for k, v in sorted(c.items()):
        print(*k, v, sep="\t")
    print("total", len(rows), sep="\t")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
