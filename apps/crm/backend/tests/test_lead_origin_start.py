"""Origin facts from the bot `/start` payload (LID-5b): pure parsing."""

from app.domain.lead_origin import origin_from_start_payload as parse


def test_plain_key_is_the_form() -> None:
    origin = parse("Pricing_Page", "ru-RU")
    assert (origin.form, origin.utm, origin.lang) == ("pricing_page", None, "ru")


def test_compact_form_gives_utm() -> None:
    origin = parse("src-tg_med-cpc_cmp-spring-2026")
    assert origin.utm == {
        "utm_source": "tg",
        "utm_medium": "cpc",
        "utm_campaign": "spring-2026",
    }


def test_unknown_language_is_dropped() -> None:
    assert parse("x", "de").lang is None


def test_reserved_and_unsafe_payloads_give_nothing() -> None:
    for raw in (
        "staff_AbCdEfGhIjKlMnOp",
        "deal_12",
        "tg_abc",
        "lead_1_2_3",
        "a b",
        "a" * 65,
        "ü",
        "",
        None,
    ):
        assert parse(raw).is_empty(), raw
