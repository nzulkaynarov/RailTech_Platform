"""Типы входящих писем (MAIL-TYPES): правила отправителя и разбор ответа ИИ по справочнику."""

import pytest

from app.domain.mail_types import (
    ACTIONS,
    COLORS,
    ICONS,
    SEED,
    ActiveType,
    best_rule,
    normalize_pattern,
    parse_verdict,
    pick_type,
    types_block,
)

TYPES = [
    ActiveType("client_request", ("Запрос клиента", "Mijoz so'rovi", "Customer request")),
    ActiveType("official", ("Официальное письмо", "Rasmiy xat", "Official letter")),
]


def test_seed_is_consistent_with_closed_sets() -> None:
    codes = [s.code for s in SEED]
    assert len(codes) == len(set(codes)) == 8
    assert {s.action for s in SEED} <= set(ACTIONS)
    assert {s.color for s in SEED} <= set(COLORS)
    assert {s.icon for s in SEED} <= set(ICONS)
    # каждое действие списка используется стартовым набором — набор показывает все возможности
    assert {s.action for s in SEED} == set(ACTIONS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("*@soliq.uz", "soliq.uz"),
        ("@Soliq.UZ", "soliq.uz"),
        (" soliq.uz ", "soliq.uz"),
        ("Ivan@Firma.uz", "ivan@firma.uz"),
        ("", None),
        ("soliq", None),
        ("a b@c.uz", None),
        ("*@*.uz", None),
        ("http://soliq.uz", None),
    ],
)
def test_normalize_pattern(raw: str, expected: str | None) -> None:
    assert normalize_pattern(raw) == expected


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        ("info@soliq.uz", "tax"),
        ("INFO@Soliq.UZ", "tax"),
        ("noreply@mail.soliq.uz", "tax"),
        ("boss@soliq.uz", "boss"),  # адрес целиком точнее домена
        ("x@notsoliq.uz", None),  # граница по точке: чужое окончание не подходит
        ("x@soliq.uz.evil.com", None),
        ("", None),
        ("no-at-sign", None),
    ],
)
def test_best_rule(sender: str, expected: str | None) -> None:
    rules = [("soliq.uz", "tax"), ("boss@soliq.uz", "boss")]
    assert best_rule(sender, rules) == expected


def test_longer_domain_is_more_specific() -> None:
    rules = [("uz", "country"), ("bank.uz", "bank")]
    assert best_rule("a@x.bank.uz", rules) == "bank"


def test_types_block_comes_from_data() -> None:
    block = types_block(TYPES)
    assert "`client_request` — Запрос клиента" in block
    assert "`official`" in block
    assert "покупатель" not in block


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("client_request", "client_request"),
        ("Client_Request", "client_request"),
        ("Запрос клиента", "client_request"),
        ("official letter", "official"),
        ("«Rasmiy xat».", "official"),
        ("spam", None),  # такого типа нет среди действующих (отключён или выдуман)
        ("buyer", None),
        ("", None),
        (None, None),
        (5, None),
    ],
)
def test_pick_type(value: object, expected: str | None) -> None:
    assert pick_type(value, TYPES) == expected


def test_parse_verdict_known_type() -> None:
    verdict, problem = parse_verdict(
        '{"type": "official", "summary": "Налоговая просит сверку."}', TYPES
    )
    assert problem is None
    assert verdict is not None
    assert (verdict.type_code, verdict.summary) == ("official", "Налоговая просит сверку.")


def test_parse_verdict_disabled_or_unknown_type_leaves_type_empty() -> None:
    verdict, problem = parse_verdict('{"type": "spam", "summary": "Реклама."}', TYPES)
    assert verdict is not None
    assert verdict.type_code is None
    assert verdict.summary == "Реклама."
    assert problem == "unknown_type"


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        (None, "not_json"),
        ("не json", "not_json"),
        ("[1, 2]", "no_object"),
        ('{"type": "official", "summary": "  "}', "empty_summary"),
        ('{"type": "official"}', "empty_summary"),
    ],
)
def test_parse_verdict_garbage(raw: str | None, problem: str) -> None:
    assert parse_verdict(raw, TYPES) == (None, problem)


def test_parse_verdict_strips_fences_and_control_chars() -> None:
    raw = '```json\n{"type": "client_request", "summary": "Нужны\\nшпалы"}\n```'
    verdict, _ = parse_verdict(raw, TYPES)
    assert verdict is not None
    assert verdict.summary == "Нужны шпалы"


@pytest.mark.parametrize(
    "raw",
    [
        # форматы ответа, которые встречаются у моделей через LiteLLM
        '```\n{"type": "official", "summary": "Письмо банка"}\n```',
        'Вот ответ:\n{"type": "official", "summary": "Письмо банка"}\nНадеюсь, помог.',
        '{"type": " Official ", "summary": "Письмо банка", "extra": 1}',
        '[1, 2] {"type": "official", "summary": "Письмо банка"}',
    ],
)
def test_parse_verdict_tolerates_model_formats(raw: str) -> None:
    verdict, problem = parse_verdict(raw, TYPES)
    assert problem is None
    assert verdict is not None
    assert verdict.type_code == "official"
