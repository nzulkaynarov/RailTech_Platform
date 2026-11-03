import json
from pathlib import Path
from typing import Any

import pytest

from app.security.pii import (
    DEFAULT_POLICY,
    PiiPolicy,
    langfuse_mask,
    mask_business,
    mask_for_model,
    mask_text,
    mask_value,
    structlog_processor,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Позвоните на +998 90 123-45-67", "Позвоните на [number]"),
        ("мой номер 901234567", "мой номер [number]"),
        ("ИНН 305123456 и почта ivan.petrov@mail.uz", "ИНН [number] и почта [email]"),
        ("Карта 4111 1111 1111 1111", "Карта [number]"),
        ("Нужно 3 кассы и 10 трекеров в 2026 году", "Нужно 3 кассы и 10 трекеров в 2026 году"),
        ("Тариф стоит 150 000 сум", "Тариф стоит 150 000 сум"),
        # W18A-P2: паспорт РУз, ПИНФЛ, дата рождения — перед вызовом модели
        ("паспорт AA1234567 выдан", "паспорт [passport] выдан"),
        ("серия AB 7654321", "серия [passport]"),
        ("ПИНФЛ 31234567890123", "ПИНФЛ [number]"),
        ("Дата рождения: 12.03.1985, г. Ташкент", "Дата рождения: [date], г. Ташкент"),
        ("акт от 31.10.2026 на сумму", "акт от 31.10.2026 на сумму"),
        ("счёт 20208000900123456001", "счёт [number]"),
    ],
)
def test_mask_text(text: str, expected: str) -> None:
    assert mask_text(text) == expected


def test_mask_nested() -> None:
    assert mask_value({"a": ["x@y.com", 5], "b": ("+998901234567",)}) == {
        "a": ["[email]", 5],
        "b": ("[number]",),
    }


def test_structlog_processor_keeps_safe_keys() -> None:
    event = {"event": "msg +998901234567", "lead_id": 7, "text": "+998901234567"}
    assert structlog_processor(None, "info", event) == {
        "event": "msg +998901234567",
        "lead_id": 7,
        "text": "[number]",
    }


def test_langfuse_mask_signature() -> None:
    assert langfuse_mask(data={"input": "a@b.co"}) == {"input": "[email]"}


# PD-BIZ (владелец 2026-11-03): «Деловая» скрывает только паспорт, ПИНФЛ, карты и даты рождения.
BUSINESS_MASKED = [
    ("паспорт AA1234567 выдан", "паспорт [passport] выдан"),
    ("серия AB 7654321", "серия [passport]"),
    ("ПИНФЛ 31234567890123", "ПИНФЛ [pinfl]"),
    ("ПИНФЛ: 3 1234 567890123", "ПИНФЛ: [pinfl]"),
    ("31234567890123 — личный номер", "[pinfl] — личный номер"),
    ("Карта 4111 1111 1111 1111", "Карта [card]"),
    ("карта 4111-1111-1111-1111 и всё", "карта [card] и всё"),
    ("карта 4111111111111111", "карта [card]"),
    ("Дата рождения: 12.03.1985, г. Ташкент", "Дата рождения: [date], г. Ташкент"),
    ("д.р. 01/02/90", "д.р. [date]"),
    ("Tug'ilgan sana: 12.03.1985", "Tug'ilgan sana: [date]"),
    ("tug‘ilgan kun 5.6.1990", "tug‘ilgan kun [date]"),
]
BUSINESS_KEPT = [
    "ИНН 305123456",
    "р/с 20208000900123456001, МФО 00014",
    "Телефон +998 90 123-45-67 и 901234567",
    "почта ivan.petrov@mail.uz",
    "Иванов Иван Иванович, г. Ташкент, ул. Навои, 5",
    "акт от 31.10.2026 на сумму 150 000 сум",
    "Нужно 3 кассы и 10 трекеров в 2026 году",
    "номер 4111 1111 1111 1112",  # не проходит проверку Луна — не карта
    "счёт 2020 8000 9001 2345 6001",  # 20 цифр группами — расчётный счёт, не карта
]


@pytest.mark.parametrize(("text", "expected"), BUSINESS_MASKED)
def test_business_masks_only_personal_ids(text: str, expected: str) -> None:
    assert mask_for_model(text, "business") == expected
    assert mask_business(text) == expected


@pytest.mark.parametrize("text", BUSINESS_KEPT)
def test_business_keeps_company_requisites(text: str) -> None:
    assert mask_for_model(text, "business") == text


def test_business_is_the_default() -> None:
    assert DEFAULT_POLICY == "business"
    assert (
        mask_for_model("ИНН 305123456, тел. +998901234567") == "ИНН 305123456, тел. +998901234567"
    )


@pytest.mark.parametrize("policy", ["business", "strict"])
def test_both_policies_hide_personal_ids(policy: PiiPolicy) -> None:
    masked = mask_for_model(
        "AA1234567, 31234567890123, 4111 1111 1111 1111, д.р. 12.03.1985", policy
    )
    for secret in ("AA1234567", "31234567890123", "4111", "12.03.1985"):
        assert secret not in masked


@pytest.mark.parametrize(
    "text",
    [
        "Позвоните на +998 90 123-45-67",
        "ИНН 305123456 и почта ivan.petrov@mail.uz",
        "Карта 4111 1111 1111 1111",
        "ПИНФЛ 31234567890123",
        "счёт 20208000900123456001",
        "Дата рождения: 12.03.1985, г. Ташкент",
        "паспорт AA1234567 выдан",
        "Тариф стоит 150 000 сум",
    ],
)
def test_strict_is_the_old_behaviour(text: str) -> None:
    assert mask_for_model(text, "strict") == mask_text(text)


def test_strict_still_hides_requisites() -> None:
    masked = mask_for_model(
        "ИНН 305123456, р/с 20208000900123456001, +998901234567, a@b.uz", "strict"
    )
    assert masked == "ИНН [number], р/с [number], [number], [email]"


def test_logs_stay_strict_whatever_the_policy() -> None:
    """Логи и трейсы не ослабляются: процессор structlog и Langfuse маскируют по-прежнему всё."""
    event = {"event": "x", "text": "ИНН 305123456 +998901234567 a@b.uz"}
    assert structlog_processor(None, "info", event)["text"] == "ИНН [number] [number] [email]"
    assert langfuse_mask(data="ИНН 305123456") == "ИНН [number]"


# Общие векторы с EDS (тот же файл читает EDS): строки те же — результат тот же.
VECTORS = json.loads(
    Path(__file__)
    .parents[6]
    .joinpath("packages/contracts/pii/policy-vectors.json")
    .read_text(encoding="utf-8")
)["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["text"][:50] for v in VECTORS])
def test_shared_vectors(vector: dict[str, Any]) -> None:
    text = str(vector["text"])
    business, strict = mask_for_model(text, "business"), mask_for_model(text, "strict")
    for hidden in vector["business_hidden"]:
        assert hidden not in business, (hidden, business)
    for kept in vector["business_kept"]:
        assert kept in business, (kept, business)
    for hidden in vector["strict_hidden"]:
        assert hidden not in strict, (hidden, strict)
