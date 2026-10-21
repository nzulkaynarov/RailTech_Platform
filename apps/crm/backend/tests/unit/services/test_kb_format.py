"""Проверка формата документа базы знаний при загрузке (M5-CRM-02, docs/kb/FORMAT.md)."""

from pathlib import Path

import pytest

from app.domain.errors import Reason, ValidationFailedError
from app.services.kb import format as kb_format
from app.services.kb.chunking import chunk_document
from app.services.kb.format import MAX_DOCUMENT_BYTES, split_front_matter, validate_document
from app.services.kb.markdown_convert import markdown_to_document

EXAMPLE = Path(__file__).resolve().parents[6] / "docs" / "kb" / "example.md"
HEAD = "---\ntitle: T\nlanguage: ru\nsource: Прайс 2026\nupdated: 2026-10-21\n---\n"
GOOD = HEAD + "# Тема\n\n## Раздел\n\nТекст.\n"


def rule_of(content: str | bytes, language: str | None = None) -> str:
    data = content if isinstance(content, bytes) else content.encode()
    with pytest.raises(ValidationFailedError) as err:
        validate_document(data, language=language)
    assert err.value.details["reason"] == Reason.KB_FORMAT.value
    messages = err.value.details["messages"]
    assert isinstance(messages, dict)
    assert set(messages) == {"ru", "uz", "en"}
    assert all(messages.values())
    assert err.value.details["detail"] == messages["ru"]
    return str(err.value.details["rule"])


def test_example_document_is_valid_and_chunks() -> None:
    parsed = validate_document(EXAMPLE.read_bytes(), language="ru")
    assert parsed.meta["language"] == "ru"
    drafts = chunk_document(markdown_to_document("example.md", parsed.body))
    paths = {d.heading_path for d in drafts}
    assert any(p and p.endswith("Гарантийные сроки") for p in paths)
    assert any("RT-300" in d.content for d in drafts)


def test_minimal_document_is_valid() -> None:
    assert validate_document(GOOD.encode()).meta["title"] == "T"
    assert validate_document(GOOD.encode(), language="ru")


def test_optional_fields_are_accepted() -> None:
    doc = GOOD.replace("---\n# ", "tags: [a, b]\naudience: клиенты\n---\n# ", 1)
    assert validate_document(doc.encode()).meta["tags"] == ["a", "b"]


def test_front_matter_missing() -> None:
    assert rule_of("# Тема\n\nТекст") == "front_matter_missing"
    assert rule_of("\n---\ntitle: T\n---\n# Т") == "front_matter_missing"


def test_front_matter_invalid_yaml() -> None:
    assert rule_of("---\n: : [\n---\n# Т") == "front_matter_invalid"
    assert rule_of("---\n- a\n- b\n---\n# Т") == "front_matter_invalid"


@pytest.mark.parametrize("name", ["title", "language", "source", "updated"])
def test_required_field_missing(name: str) -> None:
    lines = [ln for ln in HEAD.splitlines() if not ln.startswith(f"{name}:")]
    with pytest.raises(ValidationFailedError) as err:
        validate_document(("\n".join(lines) + "\n# Т\n").encode())
    assert err.value.details["rule"] == "field_missing"
    assert err.value.details["missing"] == name


def test_empty_required_field_counts_as_missing() -> None:
    assert rule_of(GOOD.replace("source: Прайс 2026", "source: ''")) == "field_missing"


def test_language_rules() -> None:
    assert rule_of(GOOD.replace("language: ru", "language: de")) == "language_invalid"
    assert rule_of(GOOD, language="uz") == "language_mismatch"


@pytest.mark.parametrize("value", ["21.10.2026", "2026-10-21T10:00:00", "вчера", "2026"])
def test_updated_must_be_a_date(value: str) -> None:
    assert rule_of(GOOD.replace("2026-10-21", value)) == "updated_invalid"


def test_tags_must_be_list() -> None:
    assert rule_of(GOOD.replace("---\n# ", "tags: abc\n---\n# ", 1)) == "tags_invalid"


def test_field_types() -> None:
    assert rule_of(GOOD.replace("title: T", "title: [a]")) == "field_type"


def test_h1_exactly_one() -> None:
    assert rule_of(HEAD + "## Раздел\n\nТекст") == "h1_missing"
    assert rule_of(HEAD + "# Один\n\n# Два\n") == "h1_multiple"


def test_hash_in_code_fence_is_not_a_heading() -> None:
    fenced = HEAD + "# Тема\n\n```\n# комментарий\n```\n"
    assert validate_document(fenced.encode())


def test_images_and_file_links_are_refused() -> None:
    assert rule_of(GOOD + "\n![схема](scheme.png)\n") == "images"
    assert rule_of(GOOD + '\n<img src="a.png">\n') == "images"
    assert rule_of(GOOD + "\nСм. [прайс](files/price.PDF)\n") == "file_links"
    assert validate_document((GOOD + "\nСм. [сайт](https://railtech.uz/about)\n").encode())


def test_size_limit() -> None:
    big = GOOD + "строка\n" * (MAX_DOCUMENT_BYTES // 12)
    assert len(big.encode()) > MAX_DOCUMENT_BYTES
    assert rule_of(big) == "size"
    almost = GOOD + "a" * (MAX_DOCUMENT_BYTES - len(GOOD.encode()) - 1)
    assert validate_document(almost.encode())


def test_encoding_must_be_utf8() -> None:
    assert (
        rule_of(GOOD.encode("cp1251").replace(b"Text", b"x") + "я".encode("cp1251")) == "encoding"
    )


def test_bom_is_tolerated() -> None:
    assert validate_document(b"\xef\xbb\xbf" + GOOD.encode("utf-8")).meta["title"] == "T"
    assert split_front_matter("﻿" + GOOD).meta["title"] == "T"


def test_not_markdown_error_has_three_languages() -> None:
    err = kb_format.not_markdown_error()
    assert err.details["reason"] == Reason.KB_MARKDOWN_ONLY.value
    messages = err.details["messages"]
    assert isinstance(messages, dict)
    assert set(messages) == {"ru", "uz", "en"}
