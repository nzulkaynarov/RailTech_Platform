"""Lead origin facts: where a lead came from (LID-5). Pure functions, no I/O.

The channel itself is `Lead.source` (`lead_sources.LeadSource`). This module holds the facts
that refine it for the public web form: form key, landing page path, referrer, UTM parameters
and the landing language. Everything is cleaned and bounded here; nothing is free text from staff.
"""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

UTM_KEYS: Final = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
_UTM_MAX: Final = 128
_FORM_MAX: Final = 64
_URL_MAX: Final = 512
_LANGS: Final = frozenset({"ru", "uz", "en"})
_FORM_KEY: Final = re.compile(r"[^a-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class LeadOrigin:
    form: str | None = None
    page: str | None = None
    referrer: str | None = None
    utm: dict[str, str] | None = None
    lang: str | None = None

    def is_empty(self) -> bool:
        return not (self.form or self.page or self.referrer or self.utm or self.lang)


def _form_key(raw: str | None) -> str | None:
    key = _FORM_KEY.sub("_", (raw or "").strip().lower()).strip("_")
    return key[:_FORM_MAX] or None


def _page_path(raw: str | None) -> str | None:
    """Path of the landing page; scheme, host, query and fragment are dropped."""
    text = (raw or "").strip()
    if not text:
        return None
    path = urlsplit(text).path if "://" in text or text.startswith("//") else text.split("?")[0]
    path = path.split("#")[0]
    if not path.startswith("/"):
        path = "/" + path
    return path[:_URL_MAX]


def _referrer(raw: str | None) -> str | None:
    """Referrer as host + path: the query string may carry personal data, so it is dropped."""
    text = (raw or "").strip()
    if not text:
        return None
    parts = urlsplit(text if "://" in text else "//" + text)
    if not parts.netloc:
        return None
    return f"{parts.netloc}{parts.path}".rstrip("/")[:_URL_MAX] or None


def clean_utm(raw: dict[str, str | None] | None) -> dict[str, str] | None:
    out: dict[str, str] = {}
    for key in UTM_KEYS:
        value = ((raw or {}).get(key) or "").strip()
        if value:
            out[key] = value[:_UTM_MAX]
    return out or None


def build_origin(
    *,
    form: str | None = None,
    page: str | None = None,
    referrer: str | None = None,
    utm: dict[str, str | None] | None = None,
    lang: str | None = None,
) -> LeadOrigin:
    language = (lang or "").strip().lower()
    return LeadOrigin(
        form=_form_key(form),
        page=_page_path(page),
        referrer=_referrer(referrer),
        utm=clean_utm(utm),
        lang=language if language in _LANGS else None,
    )
