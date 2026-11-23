"""Lead origin facts (LID-5): cleaning of form key, page, referrer, UTM and language."""

import pytest

from app.domain.lead_origin import build_origin


def test_utm_kept_and_bounded() -> None:
    origin = build_origin(
        utm={"utm_source": "tg", "utm_campaign": "x" * 500, "utm_term": "  ", "bogus": "1"}
    )
    assert origin.utm is not None
    assert origin.utm["utm_source"] == "tg"
    assert len(origin.utm["utm_campaign"]) == 128
    assert set(origin.utm) == {"utm_source", "utm_campaign"}


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ("https://railtech.uz/pos?utm_source=a#x", "/pos"),
        ("/contacts?x=1", "/contacts"),
        ("pricing", "/pricing"),
        (None, None),
        ("  ", None),
    ],
)
def test_page_is_path_only(page: str | None, expected: str | None) -> None:
    assert build_origin(page=page).page == expected


def test_referrer_drops_query_and_scheme() -> None:
    origin = build_origin(referrer="https://www.google.com/search?q=secret+name")
    assert origin.referrer == "www.google.com/search"


def test_form_key_and_language_normalised() -> None:
    origin = build_origin(form=" Request Form! ", lang="UZ")
    assert (origin.form, origin.lang) == ("request_form", "uz")
    assert build_origin(lang="de").lang is None
    assert build_origin().is_empty()
