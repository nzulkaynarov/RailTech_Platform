"""Маска персональных данных перед моделью (EDS-REG): правила CRM (`apps/crm/backend/tests` — те же примеры) и
нумерованные метки чисел с локальным возвратом."""

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
    result = mask_numbered("Исх. № 1234567/КЦ от 28.10.2026. ИНН 301234567. Тел. +998 90 123 45 67, a@b.uz")
    assert result.text == "Исх. № [number_1]/КЦ от 28.10.2026. ИНН [number_2]. Тел. [number_3], [email]"
    assert result.numbers == ["1234567", "301234567", "+998 90 123 45 67"]
    assert result.unmask("[number_1]/КЦ") == "1234567/КЦ"
    assert result.unmask("[number_9]") == "[number_9]"
    assert result.has_tokens("[number_2]") and not result.has_tokens("04-12")
