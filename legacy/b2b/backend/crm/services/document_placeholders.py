"""Safe placeholder substitution + HTML sanitisation for «Документы 2.0».

SECURITY — this module NEVER runs Django's template engine (or any engine) on a
user-authored template body: that would be a server-side template injection (SSTI)
hole. Instead it does a FLAT `{{code}}` replacement restricted to a whitelist of
resolvers, and HTML-escapes every substituted VALUE before insertion (so a value
that itself contains `<script>` can't inject markup — defence against stored XSS via
deal/company data).

The template BODY is sanitised on save via `sanitize_template_html` — a stdlib
`html.parser` allowlist (bleach / nh3 are NOT project dependencies and can't be
added without touching the hashed pip lock; nh3 is the recommended harden-forward
upgrade if it ever lands in requirements).
"""

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Callable, Optional

from django.utils.html import escape

# {{ code }} — code is a dotted whitelist key (deal.number, company.name, today …).
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


@dataclass
class PlaceholderContext:
    """The resolved objects a template may reference. All optional — a missing
    object yields an empty substitution (never a crash)."""

    company: object = None  # the document OWNER company (company.*)
    deal: object = None
    contact: object = None
    quote: object = None
    contract: object = None
    user: object = None


def extract_placeholders(body_html: str) -> list:
    """Ordered, de-duplicated list of `{{code}}` tokens found in the body."""
    seen = []
    for match in PLACEHOLDER_RE.finditer(body_html or ""):
        code = match.group(1).strip()
        if code not in seen:
            seen.append(code)
    return seen


def _fmt(value) -> str:
    return "" if value is None else str(value)


# ── Whitelist resolver registry ─────────────────────────────────────────────
# Each resolver takes a PlaceholderContext and returns a raw (UN-escaped) string;
# escaping happens centrally in _render_from_values. Anything NOT in this dict is
# an unknown placeholder → left verbatim + reported as a warning.
def _counterparty_name(ctx: PlaceholderContext) -> str:
    if ctx.contact is not None:
        return _fmt(ctx.contact.name)
    if ctx.deal is not None and ctx.deal.company_id:
        return _fmt(ctx.deal.company.name)
    return ""


def _counterparty_inn(ctx: PlaceholderContext) -> str:
    if ctx.contact is not None and ctx.contact.company_id:
        return _fmt(ctx.contact.company.inn)
    if ctx.deal is not None and ctx.deal.company_id:
        return _fmt(ctx.deal.company.inn)
    return ""


RESOLVERS: dict = {
    "deal.number": lambda ctx: _fmt(f"#{ctx.deal.id}") if ctx.deal else "",
    "deal.title": lambda ctx: _fmt(ctx.deal.title) if ctx.deal else "",
    "company.name": lambda ctx: _fmt(ctx.company.name) if ctx.company else "",
    "company.inn": lambda ctx: _fmt(ctx.company.inn) if ctx.company else "",
    "company.address": lambda ctx: _fmt(ctx.company.legal_address) if ctx.company else "",
    "counterparty.name": _counterparty_name,
    "counterparty.inn": _counterparty_inn,
    "quote.number": lambda ctx: _fmt(ctx.quote.number) if ctx.quote else "",
    "quote.total": lambda ctx: _fmt(ctx.quote.total_incl_vat) if ctx.quote else "",
    "contract.number": lambda ctx: _fmt(ctx.contract.number) if ctx.contract else "",
    "user.full_name": lambda ctx: _fmt(ctx.user.get_full_name() or ctx.user.email) if ctx.user else "",
    "user.email": lambda ctx: _fmt(ctx.user.email) if ctx.user else "",
    "today": lambda ctx: date.today().strftime("%d.%m.%Y"),
}

# Advertised catalogue for the UI (settings placeholder helper), split into two GROUPS (T1-c):
#   • dynamic  — per-document data (сделка / контрагент / КП / договор / автор / дата) that the
#                letterhead can NOT know: this is what a template body is for.
#   • company  — the OWNER company's own requisites. They are already printed in the branded шапка +
#                колонтитул (crm/_document_base.html), so repeating them in the body duplicates the
#                letterhead. Kept in the catalogue (a rare template may still want them inline) but
#                flagged «уже в шапке» so the editor steers the author away from the dupe.
# `label` is a Russian fallback; the SPA re-labels group HEADINGS via i18n keyed on `key` (Rule 5).
PLACEHOLDER_GROUPS = [
    {
        "key": "dynamic",
        "label": "Динамические данные",
        "items": [
            {"code": "deal.number", "label": "Номер сделки"},
            {"code": "deal.title", "label": "Название сделки"},
            {"code": "counterparty.name", "label": "Контрагент — название"},
            {"code": "counterparty.inn", "label": "Контрагент — ИНН"},
            {"code": "quote.number", "label": "Номер КП"},
            {"code": "quote.total", "label": "Сумма КП"},
            {"code": "contract.number", "label": "Номер договора"},
            {"code": "user.full_name", "label": "Ваше ФИО"},
            {"code": "user.email", "label": "Ваш email"},
            {"code": "today", "label": "Сегодняшняя дата"},
        ],
    },
    {
        "key": "company",
        "label": "Реквизиты компании (уже в шапке)",
        "items": [
            {"code": "company.name", "label": "Ваша компания — название"},
            {"code": "company.inn", "label": "Ваша компания — ИНН"},
            {"code": "company.address", "label": "Ваша компания — адрес"},
        ],
    },
]


def _legal_group() -> dict:
    """Третья группа каталога — структурные блоки и скаляры юридических видов (договор /
    счёт / акт, E1b). Собирается из каталогов `document_blocks` — единственного источника,
    с которым сверяется и проверка целостности (E2): разъехаться они не могут."""
    from .document_blocks import DOCUMENT_BLOCKS, DOCUMENT_SCALARS, DOCUMENT_WORDING_TOKENS

    wording_labels = {
        "doc.act_closing": "Оговорка акта (настройка «Формулировки»)",
        "doc.contract_acceptance": "Приёмка и качество (настройка «Формулировки»)",
        "doc.contract_liability": "Ответственность сторон (настройка «Формулировки»)",
    }
    items = (
        [{"code": code, "label": label} for code, label in DOCUMENT_BLOCKS.items()]
        + [{"code": code, "label": wording_labels.get(code, code)} for code in DOCUMENT_WORDING_TOKENS]
        + [{"code": code, "label": label} for code, label in DOCUMENT_SCALARS.items()]
    )
    return {"key": "legal_blocks", "label": "Юридические документы (договор / счёт / акт)", "items": items}


PLACEHOLDER_GROUPS.append(_legal_group())

# Flat {code: label} projection of the grouped catalogue — kept for any consumer that just needs the
# label of a code (derived from PLACEHOLDER_GROUPS so the two never drift).
PLACEHOLDER_CATALOG = {item["code"]: item["label"] for group in PLACEHOLDER_GROUPS for item in group["items"]}


def _label_key(code: str) -> str:
    """`doc.items_table` → `docPlaceholders.doc_items_table` — ключ словаря SPA.

    L1 (spec-bilingual-ru-en): по проводам едет КОД, слово подставляет клиент. Раньше
    каталог отдавал русские `label`, и редактор шаблонов оставался русским даже в
    английском интерфейсе. `label` сохранён рядом как RU-fallback: незнакомый ключ
    печатается им, а не пустотой.
    """
    return "docPlaceholders." + code.replace(".", "_")


def placeholder_groups_with_keys() -> list:
    """Каталог для SPA: к каждому коду добавлен `label_key`, группам — `label_key` группы."""
    return [
        {
            "key": group["key"],
            "label": group["label"],
            "label_key": f"docTemplatesSettings.placeholderGroups.{group['key']}",
            "items": [
                {"code": item["code"], "label": item["label"], "label_key": _label_key(item["code"])}
                for item in group["items"]
            ],
        }
        for group in PLACEHOLDER_GROUPS
    ]


def _render_from_values(body_html: str, values: dict) -> str:
    """Flat-replace `{{code}}` with the ESCAPED snapshot value; leave unknown tokens
    verbatim. Used both at generation time and for DRAFT re-render off a stored snapshot."""

    def _sub(match: "re.Match") -> str:
        code = match.group(1).strip()
        if code in values:
            return escape(_fmt(values[code]))
        return match.group(0)

    return PLACEHOLDER_RE.sub(_sub, body_html or "")


def render_template(body_html: str, context: PlaceholderContext):
    """Resolve every known placeholder against `context`, returning
    ``(html, values, warnings)``:
      * ``values``   — snapshot dict {code: raw value} for whitelisted codes used;
      * ``warnings`` — unknown placeholder codes (left verbatim in the html).
    """
    values = {}
    warnings = []
    for code in extract_placeholders(body_html):
        resolver: Optional[Callable] = RESOLVERS.get(code)
        if resolver is None:
            warnings.append(code)
            continue
        values[code] = resolver(context)
    return _render_from_values(body_html, values), values, warnings


def render_from_values(body_html: str, values: dict) -> str:
    """Public re-render entrypoint (DRAFT edit): re-substitute a stored snapshot."""
    return _render_from_values(body_html, values)


# ── HTML sanitiser (stdlib allowlist) ───────────────────────────────────────
_ALLOWED_TAGS = {
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "strong",
    "em",
    "u",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "div",
    "span",
    "hr",
    "img",
    "a",
}
# Void tags that must self-close in the sanitised output.
_VOID_TAGS = {"br", "hr", "img"}
# Tags whose text content must be dropped entirely (script/style are parsed in
# CDATA mode; iframe/object embed remote content).
_DROP_CONTENT_TAGS = {"script", "style", "iframe", "object", "embed"}
# Per-tag attribute allowlist. Everything else (incl. any `on*` handler, style,
# class, id) is stripped.
_ALLOWED_ATTRS = {
    "img": {"src", "alt"},
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
# Per-attribute URL policy. `href` (links) must NOT accept `data:` at all. `src` (only <img>) is
# restricted to an inline raster data URI — NEVER a remote http(s)/relative URL. Rationale (T3):
# document bodies are rendered to PDF by WeasyPrint, whose default url_fetcher performs a
# SERVER-SIDE GET of any remote `src` at render time. The app-VPS sits on the private LAN to the
# DB-VPS, so an author-chosen `<img src="http://10.0.0.2:.../">` / metadata URL would be a blind
# SSRF. Inline base64 rasters carry no fetch; data:image/svg+xml stays banned (SVG can run script).
# The letterhead logo is a company FileField rendered OUTSIDE this body sanitizer, so it is unaffected.
_SAFE_HREF_RE = re.compile(r"^(https?:|mailto:|tel:|/|#)", re.IGNORECASE)
_SAFE_SRC_RE = re.compile(r"^data:image/(?:png|jpe?g|gif|webp);base64,", re.IGNORECASE)
_URL_ATTR_POLICY = {"href": _SAFE_HREF_RE, "src": _SAFE_SRC_RE}


def _clean_attrs(tag: str, attrs) -> str:
    allowed = _ALLOWED_ATTRS.get(tag, set())
    parts = []
    for name, value in attrs:
        lname = (name or "").lower()
        if lname.startswith("on") or lname not in allowed:
            continue
        if lname in _URL_ATTR_POLICY:
            candidate = (value or "").strip()
            if not _URL_ATTR_POLICY[lname].match(candidate):
                continue  # drop javascript:/vbscript:/data:svg/unknown schemes
        # Django's escape() always escapes quotes (unlike stdlib html.escape, it takes no
        # `quote` kwarg) — so an attribute value can't break out of its double-quoted context.
        parts.append(f' {lname}="{escape(value or "")}"')
    return "".join(parts)


class _SanitizingParser(HTMLParser):
    """Allowlist sanitiser: keeps only whitelisted tags/attributes, escapes text,
    and drops the content of script/style/iframe. Not a security boundary on its own
    — paired with value-escaping at substitution time (nh3 is the harden-forward path)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._drop_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if tag in _ALLOWED_TAGS:
            close = " /" if tag in _VOID_TAGS else ""
            self.out.append(f"<{tag}{_clean_attrs(tag, attrs)}{close}>")

    def handle_startendtag(self, tag, attrs):
        if tag in _DROP_CONTENT_TAGS or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{_clean_attrs(tag, attrs)} />")

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT_TAGS:
            if self._drop_depth > 0:
                self._drop_depth -= 1
            return
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self._drop_depth == 0:
            self.out.append(escape(data))

    def result(self) -> str:
        return "".join(self.out)


def sanitize_template_html(html: str) -> str:
    """Return a sanitised copy of `html`: only whitelisted tags/attributes survive,
    text is escaped, and script/style/iframe bodies are dropped."""
    if not html:
        return ""
    parser = _SanitizingParser()
    parser.feed(html)
    parser.close()
    return parser.result()
