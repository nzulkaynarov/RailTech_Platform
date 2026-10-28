"""Правила статей компании (W18A-P5): проверка значений без БД."""

import pytest

from app.domain import company_articles as rules
from app.domain.errors import Reason


def test_title_is_trimmed_and_whitespace_collapsed() -> None:
    assert rules.checked_title("  Как   согласуем\n договор ") == "Как согласуем договор"


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("   ", "article_title_empty"),
        ("", "article_title_empty"),
        ("я" * (rules.TITLE_MAX_LEN + 1), "article_title_too_long"),
    ],
)
def test_bad_title_carries_reason_and_field(title: str, reason: str) -> None:
    with pytest.raises(rules.ArticleValueError) as caught:
        rules.checked_title(title)
    assert (caught.value.reason, caught.value.field) == (reason, "title")


def test_title_at_the_limit_is_accepted() -> None:
    assert len(rules.checked_title("я" * rules.TITLE_MAX_LEN)) == rules.TITLE_MAX_LEN


@pytest.mark.parametrize(
    ("body", "reason"),
    [("\n \n", "article_body_empty"), ("x" * (rules.BODY_MAX_LEN + 1), "article_body_too_long")],
)
def test_bad_body_carries_reason_and_field(body: str, reason: str) -> None:
    with pytest.raises(rules.ArticleValueError) as caught:
        rules.checked_body(body)
    assert (caught.value.reason, caught.value.field) == (reason, "body")


def test_body_keeps_markdown_and_trims_the_edges() -> None:
    assert rules.checked_body("\n## Шаги\n\n- один\n") == "## Шаги\n\n- один"


def test_language_and_status_are_closed_lists() -> None:
    assert [rules.checked_language(x) for x in ("ru", "uz", "en")] == ["ru", "uz", "en"]
    assert [rules.checked_status(x) for x in ("draft", "published")] == ["draft", "published"]
    with pytest.raises(rules.ArticleValueError) as language:
        rules.checked_language("de")
    assert language.value.reason == "article_language_unknown"
    with pytest.raises(rules.ArticleValueError) as status:
        rules.checked_status("archived")
    assert (status.value.reason, status.value.field) == ("article_status_unknown", "status")


def test_every_reason_the_rules_raise_exists_in_the_error_contract() -> None:
    known = {r.value for r in Reason}
    for reason in (
        "article_title_empty",
        "article_title_too_long",
        "article_body_empty",
        "article_body_too_long",
        "article_language_unknown",
        "article_status_unknown",
    ):
        assert reason in known
