"""HTML письма (W18A-P2-4): безопасная версия для показа и текст из разметки. Чистые функции.

Санитизация — `nh3` (ammonia) по белому списку тегов, атрибутов, классов и свойств `style`; чего
в списке нет (скрипты, `style`-блоки, фреймы, формы, `meta`, `base`, `svg`, обработчики событий,
`javascript:`/`data:` в ссылках), вычищается. Картинки:

- внешние (`http`/`https`) теряют `src` и получают `data-rt-src` — интерфейс подставит адрес только
  по кнопке «Показать картинки» (трекинг-пиксели не срабатывают при открытии);
- встроенные `cid:` заменяются вложением письма (`data:` URI, только PNG/JPEG/GIF/WebP в пределах
  бюджета); нет вложения или оно отброшено белым списком — `data-rt-missing`, интерфейс рисует
  заглушку;
- `data:image/...` из самого письма остаётся для растровых типов в пределах бюджета.

Показывает такой HTML интерфейс в `iframe` с `sandbox` без `allow-scripts`, `srcdoc` и CSP
(`docs/systems/platform/CONVENTIONS.md`, статья «Входящая почта»).
"""

import base64
import html as html_lib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final
from urllib.parse import unquote

import nh3

MAX_HTML_CHARS: Final = 800_000  # больше — письмо показывается текстом
MAX_SAFE_CHARS: Final = 2_200_000
MAX_INLINE_ONE: Final = 400 * 1024
MAX_INLINE_TOTAL: Final = 1024 * 1024
RASTER_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

_TAGS: Final = (nh3.ALLOWED_TAGS - {"map", "area"}) | {"font", "span", "center"}
_CLEAN_CONTENT: Final = frozenset(
    {
        "script",
        "style",
        "head",
        "title",
        "noscript",
        "template",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
        "textarea",
        "select",
        "option",
        "audio",
        "video",
        "canvas",
        "applet",
        "frameset",
        "frame",
        "xmp",
        "noembed",
        "noframes",
    }
)
_ATTRIBUTES: Final = {
    "*": {"style", "dir", "lang", "align", "title"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "table": {"width", "border", "cellpadding", "cellspacing", "bgcolor"},
    "td": {"width", "height", "colspan", "rowspan", "valign", "bgcolor", "scope"},
    "th": {"width", "height", "colspan", "rowspan", "valign", "bgcolor", "scope"},
    "tr": {"valign", "bgcolor"},
    "col": {"width", "span"},
    "colgroup": {"width", "span"},
    "font": {"color", "size", "face"},
    "ol": {"start", "type"},
}
#: Классы нужны только для сворачивания цитаты.
QUOTE_CLASSES: Final = frozenset(
    {"gmail_quote", "gmail_attr", "yahoo_quoted", "moz-cite-prefix", "protonmail_quote"}
)
_CLASS_TAGS: Final = ("div", "blockquote", "span", "p", "table", "section")
_STYLE_PROPERTIES: Final = frozenset(
    {
        "color",
        "background",
        "background-color",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "font-variant",
        "line-height",
        "letter-spacing",
        "text-align",
        "text-decoration",
        "text-transform",
        "text-indent",
        "vertical-align",
        "white-space",
        "word-break",
        "word-spacing",
        "overflow-wrap",
        "word-wrap",
        "width",
        "max-width",
        "height",
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "margin",
        "margin-top",
        "margin-right",
        "margin-bottom",
        "margin-left",
        "border",
        "border-top",
        "border-right",
        "border-bottom",
        "border-left",
        "border-color",
        "border-style",
        "border-width",
        "border-radius",
        "border-collapse",
        "border-spacing",
        "table-layout",
        "list-style-type",
        "display",
        "direction",
    }
)
_BAD_STYLE: Final = re.compile(
    r"expression|url\s*\(|javascript|vbscript|@import|behaviou?r|binding|image-set|image\s*\(|"
    r"\bsrc\s*\(|\\|/\*|<|>",
    re.IGNORECASE,
)
_HREF_SCHEMES: Final = ("http:", "https:", "mailto:", "tel:")
_DATA_IMAGE: Final = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)$")
_IMG: Final = re.compile(r'<img((?:\s+[a-zA-Z][\w:-]*(?:="[^"]*")?)*)\s*/?>')
_ATTR: Final = re.compile(r'([a-zA-Z][\w:-]*)(?:="([^"]*)")?')
_VISIBLE: Final = re.compile(r"<img\b|[^\s<>&;]")


@dataclass(frozen=True, slots=True)
class InlineImage:
    """Вложение письма с Content-ID — кандидат для `cid:` в разметке."""

    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SafeHtml:
    html: str
    remote_images: int  # сколько внешних картинок ждут кнопки «Показать картинки»
    missing_images: int  # встроенные, которых нет среди разрешённых вложений
    inlined: frozenset[str] = frozenset()  # Content-ID вложений, показанных в тексте письма


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if attr == "style":
        return None if _BAD_STYLE.search(value) else value
    if tag == "a" and attr == "href":
        return value if value.strip().lower().startswith(_HREF_SCHEMES) else None
    if tag == "img" and attr == "src":
        low = value.strip().lower()
        ok = low.startswith(("cid:", "http://", "https://", "data:image/"))
        return value.strip() if ok else None
    return value


def _img_tag(
    attrs: str,
    inline: Mapping[str, InlineImage],
    budget: list[int],
    counts: list[int],
    used: set[str],
) -> str:
    kept: list[str] = []
    src: str | None = None
    for name, value in _ATTR.findall(attrs):
        if name.lower() == "src":
            src = html_lib.unescape(value)
        else:
            kept.append(_attr(name, value))
    if src is None:
        return f"<img{''.join(kept)}>"
    low = src.lower()
    if low.startswith(("http://", "https://")):
        counts[0] += 1
        kept.append(_attr("data-rt-src", html_lib.escape(src, quote=True)))
    else:
        data_uri = _inline_uri(src, inline, budget)
        if data_uri is not None and low.startswith("cid:"):
            used.add(_cid(src))
        if data_uri is None:
            counts[1] += 1
            kept.append(_attr("data-rt-missing", "1"))
        else:
            kept.append(_attr("src", data_uri))
    return f"<img{''.join(kept)}>"


def _attr(name: str, value: str) -> str:
    return f' {name}="{value}"'


def _cid(src: str) -> str:
    return unquote(src[4:]).strip().strip("<>").lower()


def _inline_uri(src: str, inline: Mapping[str, InlineImage], budget: list[int]) -> str | None:
    low = src.lower()
    if low.startswith("cid:"):
        image = inline.get(_cid(src))
        if image is None or image.content_type not in RASTER_TYPES:
            return None
        size = len(image.data)
        if size > MAX_INLINE_ONE or size > budget[0]:
            return None
        budget[0] -= size
        return f"data:{image.content_type};base64,{base64.b64encode(image.data).decode()}"
    found = _DATA_IMAGE.match(src.strip())
    if found is None:
        return None
    size = len(found.group(2)) * 3 // 4
    if size > MAX_INLINE_ONE or size > budget[0]:
        return None
    budget[0] -= size
    return src.strip()


def sanitize_html(raw: str, inline: Mapping[str, InlineImage] | None = None) -> SafeHtml | None:
    """HTML письма → безопасная разметка; пусто, слишком велико или без видимого — None."""
    if not raw.strip() or len(raw) > MAX_HTML_CHARS:
        return None
    cleaned = nh3.clean(
        raw,
        tags=set(_TAGS),
        clean_content_tags=set(_CLEAN_CONTENT),
        attributes={tag: set(names) for tag, names in _ATTRIBUTES.items()},
        attribute_filter=_attribute_filter,
        filter_style_properties=set(_STYLE_PROPERTIES),
        allowed_classes={tag: set(QUOTE_CLASSES) for tag in _CLASS_TAGS},
        url_schemes={"http", "https", "mailto", "tel", "cid", "data"},
        url_relative="deny",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
    )
    counts = [0, 0]
    budget = [MAX_INLINE_TOTAL]
    pool = {key.strip().strip("<>").lower(): value for key, value in (inline or {}).items()}
    used: set[str] = set()
    result = _IMG.sub(lambda m: _img_tag(m.group(1), pool, budget, counts, used), cleaned).strip()
    if not result or len(result) > MAX_SAFE_CHARS or not _VISIBLE.search(result):
        return None
    return SafeHtml(result, counts[0], counts[1], frozenset(used))


# --- Текст из HTML ------------------------------------------------------------------------------
_VOID: Final = frozenset(
    {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "wbr", "source", "param"}
)
_SKIP_TAGS: Final = frozenset({"script", "style", "head", "title", "noscript", "template"})
_BREAK_TAGS: Final = frozenset(
    {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}
)
_CELL_TAGS: Final = frozenset({"td", "th"})
_QUOTE_IDS: Final = frozenset({"divrplyfwdmsg", "appendonsend"})
_HIDDEN_STYLE: Final = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all|font-size\s*:\s*0(px|pt)?\s*(;|$)"
    r"|max-height\s*:\s*0(px|pt)?\s*(;|$)",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    """HTML → (основной текст, цитата): скрытое и служебное пропускается, блоки — переводами строк,
    ячейки таблицы — пробелом; `blockquote`, `gmail_quote`, `yahoo_quoted` и т.п. — в цитату."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._main: list[str] = []
        self._quote: list[str] = []
        self._stack: list[tuple[str, str]] = []
        self._skip = 0
        self._quoted = 0

    @staticmethod
    def _mode(tag: str, attrs: list[tuple[str, str | None]]) -> str:
        values = {name: (value or "") for name, value in attrs}
        if tag in _SKIP_TAGS or "hidden" in values or _HIDDEN_STYLE.search(values.get("style", "")):
            return "skip"
        classes = set(values.get("class", "").lower().split())
        if (
            tag == "blockquote"
            or classes & QUOTE_CLASSES
            or values.get("id", "").lower() in _QUOTE_IDS
        ):
            return "quote"
        return ""

    def _emit(self, text: str) -> None:
        if not self._skip:
            (self._quote if self._quoted else self._main).append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag in _BREAK_TAGS:
                self._emit("\n")
            return
        mode = self._mode(tag, attrs)
        self._stack.append((tag, mode))
        self._skip += mode == "skip"
        self._quoted += mode == "quote"
        if tag in _BREAK_TAGS:
            self._emit("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                for _, mode in self._stack[index:]:
                    self._skip -= mode == "skip"
                    self._quoted -= mode == "quote"
                del self._stack[index:]
                break
        else:
            return
        if tag in _BREAK_TAGS:
            self._emit("\n")
        elif tag in _CELL_TAGS:
            self._emit(" ")

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def parts(self) -> tuple[str, str]:
        return "".join(self._main), "".join(self._quote)


def html_text_parts(raw: str) -> tuple[str, str]:
    """HTML → (основной текст, цитата) без нормализации; нормализует вызывающий (`mail_text`)."""
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    return parser.parts()
