"""Маска персональных данных перед моделью (EDS-REG, PD-BIZ): правила CRM (`apps/crm/backend/tests` — те же примеры),
политики «Строгая» (прежнее поведение) и «Деловая» (паспорт, ПИНФЛ, карты, даты рождения) и нумерованные метки чисел с
локальным возвратом."""

import pytest

from app.security.pii import mask_numbered, mask_text


# Те же примеры, что `apps/crm/backend/tests/unit/security/test_pii.py::test_mask_text` — правила совпадают.
@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("Позвоните на +998 90 123-45-67", "Позвоните на [number]"),
        ("мой номер 901234567", "мой номер [number]"),
        ("ИНН 305123456 и почта ivan.petrov@mail.uz", "ИНН [number] и почта [email]"),
        ("Карта 4111 1111 1111 1111", "Карта [number]"),
        ("Нужно 3 кассы и 10 трекеров в 2026 году", "Нужно 3 кассы и 10 трекеров в 2026 году"),
        ("Тариф стоит 150 000 сум", "Тариф стоит 150 000 сум"),
        ("паспорт AA1234567 выдан", "паспорт [passport] выдан"),
        ("серия AB 7654321", "серия [passport]"),
        ("ПИНФЛ 31234567890123", "ПИНФЛ [number]"),
        ("Дата рождения: 12.03.1985, г. Ташкент", "Дата рождения: [date], г. Ташкент"),
        ("акт от 31.10.2026 на сумму", "акт от 31.10.2026 на сумму"),
        ("счёт 20208000900123456001", "счёт [number]"),
        ("исх. № 04-12/3456 от 28.10.2026", "исх. № 04-12/3456 от 28.10.2026"),
    ],
)
def test_same_rules_as_crm(raw: str, masked: str) -> None:
    assert mask_text(raw) == masked


def test_numbers_get_numbered_tokens_and_come_back_locally() -> None:
    result = mask_numbered("Исх. № 1234567/КЦ от 28.10.2026. ИНН 301234567. Тел. +998 90 123 45 67, a@b.uz", "strict")
    assert result.text == "Исх. № [number_1]/КЦ от 28.10.2026. ИНН [number_2]. Тел. [number_3], [email]"
    assert result.numbers == ["1234567", "301234567", "+998 90 123 45 67"]
    assert result.unmask("[number_1]/КЦ") == "1234567/КЦ"
    assert result.unmask("[number_9]") == "[number_9]"
    assert result.has_tokens("[number_2]") and not result.has_tokens("04-12")


# Те же примеры, что `apps/crm/backend/tests/unit/security/test_pii.py` (BUSINESS_MASKED / BUSINESS_KEPT).
BUSINESS_MASKED = [
    ("паспорт AA1234567 выдан", "паспорт [passport] выдан"),
    ("серия AB 7654321", "серия [passport]"),
    ("ПИНФЛ 31234567890123", "ПИНФЛ [number_1]"),
    ("ПИНФЛ: 3 1234 567890123", "ПИНФЛ: [number_1]"),
    ("31234567890123 — личный номер", "[number_1] — личный номер"),
    ("Карта 4111 1111 1111 1111", "Карта [number_1]"),
    ("карта 4111-1111-1111-1111 и всё", "карта [number_1] и всё"),
    ("карта 4111111111111111", "карта [number_1]"),
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
    "исх. № 04-12/3456 от 28.10.2026",
    "номер 4111 1111 1111 1112",
    "счёт 2020 8000 9001 2345 6001",
]


@pytest.mark.parametrize(("raw", "masked"), BUSINESS_MASKED)
def test_business_masks_only_personal_ids(raw: str, masked: str) -> None:
    assert mask_numbered(raw, "business").text == masked


@pytest.mark.parametrize("raw", BUSINESS_KEPT)
def test_business_keeps_company_requisites(raw: str) -> None:
    result = mask_numbered(raw, "business")
    assert result.text == raw and result.numbers == []


def test_business_numbers_come_back_locally() -> None:
    result = mask_numbered("ИНН 301234567, ПИНФЛ 31234567890123, карта 4111 1111 1111 1111", "business")
    assert result.text == "ИНН 301234567, ПИНФЛ [number_1], карта [number_2]"
    assert result.unmask("[number_1] / [number_2]") == "31234567890123 / 4111 1111 1111 1111"


@pytest.mark.parametrize("raw", [raw for raw, _ in BUSINESS_MASKED] + BUSINESS_KEPT)
def test_strict_is_the_old_behaviour(raw: str) -> None:
    """«Строгая» не изменилась: тот же результат, что у `mask_text` (метки чисел вместо `[number]`)."""
    import re

    assert re.sub(r"\[number_\d+\]", "[number]", mask_numbered(raw, "strict").text) == mask_text(raw)
