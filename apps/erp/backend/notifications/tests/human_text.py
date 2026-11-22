"""Shared check for СЦ-7: a text a person reads (mail body, bell message) carries no machine artefacts."""

import re

_TAGS = re.compile(r"<[^>]+>")
_URLS = re.compile(r"https?://\S+")
_RULES = {
    "ISO date": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "raw decimal money": re.compile(r"\d{5,}\.\d{2}"),
    "database id (#123)": re.compile(r"#\d+"),
    "plural stub (и)": re.compile(r"\(и\)"),
    "raw channel code": re.compile(r"\b(cabinet|email|telegram)\b"),
}


def assert_human_text(text: str) -> None:
    """No ISO dates, no unformatted `12345.00`, no `#<id>`, no «(и)», no raw channel codes (tags and URLs ignored)."""
    visible = _URLS.sub(" ", _TAGS.sub(" ", text or ""))
    for name, pattern in _RULES.items():
        found = pattern.search(visible)
        assert found is None, f"{name} in text: «{found.group(0)}» — {visible.strip()[:200]!r}"
