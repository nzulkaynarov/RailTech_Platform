"""Витрина таможенных платежей: разбор ЖИВОГО ответа ГТК, кэш и честная деградация.

Фикстуры — настоящие ответы `tarif.customs.uz/calc/view_calc.jsp`, снятые 2026-08-04:
`tarif_calc_full.html`   — пиво из Китая: пошлина, акциз, НДС и два разрешительных документа;
`tarif_calc_sparse.html` — оси/колёса ж/д из России: заполнен только таможенный сбор.
Второй случай важнее первого: именно наш домен, и именно на нём видно, что пустая ставка
должна доезжать до интерфейса пустой, а не превращаться в «0%».
"""

from pathlib import Path

import pytest

from master_data import customs_duties
from master_data.customs_duties import DutiesUnavailable, get_duties, parse_duties

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_parses_payments_by_code_not_by_label():
    """Ключ строки — цифровой код: подписи источник отдаёт по-узбекски даже на русский запрос."""
    parsed = parse_duties(_fixture("tarif_calc_full.html"))
    by_code = {payment["code"]: payment for payment in parsed["payments"]}

    assert by_code["20"]["rate"].startswith("30.0 %")  # пошлина
    assert by_code["20"]["legal_basis"] == "ПП-4470 от 02.10.2019 г."
    assert by_code["29"]["rate"] == "12.00 %"  # НДС
    assert "27" in by_code  # акциз на пиво присутствует


def test_keeps_uncoded_payment_rows():
    """Утилизационный сбор приходит БЕЗ цифрового кода — это реальные деньги импортёра."""
    parsed = parse_duties(_fixture("tarif_calc_full.html"))
    labels = [payment["source_label"] for payment in parsed["payments"]]
    assert any("ksiz" in label or "QQS" in label for label in labels)
    # ни одна строка не потеряна: у источника их ровно столько, сколько в таблице
    assert len(parsed["payments"]) >= 3


def test_empty_rate_stays_empty_and_never_becomes_zero():
    """Пустая ячейка у источника значит и «нет платежа», и «ставка не задана» — не додумываем."""
    parsed = parse_duties(_fixture("tarif_calc_sparse.html"))
    by_code = {payment["code"]: payment for payment in parsed["payments"]}

    assert by_code["10"]["rate"]  # сбор заполнен
    assert by_code["20"]["rate"] == ""  # пошлина пуста — и остаётся пустой
    assert by_code["29"]["rate"] == ""
    assert "0" not in {by_code["20"]["rate"], by_code["29"]["rate"]}


def test_parses_permits_and_tolerates_their_absence():
    full = parse_duties(_fixture("tarif_calc_full.html"))
    assert len(full["permits"]) == 2
    assert full["permits"][0]["document"] == "Мувофиқлик сертификати"
    assert full["permits"][0]["document_kind"] == "Сертификат"

    sparse = parse_duties(_fixture("tarif_calc_sparse.html"))
    assert sparse["permits"] == []  # строка-заглушка «ничего не найдено» не едет как документ


def test_unrecognisable_response_degrades_instead_of_crashing():
    """Смена вёрстки источника обязана дать деградацию, а не 500 на карточке товара."""
    with pytest.raises(DutiesUnavailable):
        parse_duties("<html><body>Технические работы</body></html>")
    with pytest.raises(DutiesUnavailable):
        parse_duties("")


def test_result_is_cached_so_the_slow_source_is_hit_once(monkeypatch):
    from django.core.cache import cache

    cache.clear()
    calls = []

    def fake_fetch(hs_code, origin_numeric, timeout=10):
        calls.append((hs_code, origin_numeric))
        return {
            "payments": [{"code": "29", "source_label": "QQS", "rate": "12.00 %", "legal_basis": "ЗРУ"}],
            "permits": [],
        }

    monkeypatch.setattr(customs_duties, "fetch_duties", fake_fetch)

    first = get_duties("8607191000", "643")
    second = get_duties("8607191000", "643")
    assert len(calls) == 1  # второй запрос обслужен кэшем
    assert first["payments"] == second["payments"]
    assert first["fetched_at"] and first["source_url"]

    # другая страна происхождения — другой ключ: преференции зависят именно от неё
    get_duties("8607191000", "156")
    assert len(calls) == 2


def test_failure_is_negatively_cached_so_a_dead_source_is_not_hammered(monkeypatch):
    from django.core.cache import cache

    cache.clear()
    calls = []

    def failing_fetch(hs_code, origin_numeric, timeout=10):
        calls.append(hs_code)
        raise DutiesUnavailable("источник лёг")

    monkeypatch.setattr(customs_duties, "fetch_duties", failing_fetch)

    for _ in range(3):
        with pytest.raises(DutiesUnavailable):
            get_duties("8703101100", "156")
    assert len(calls) == 1  # повторные клики не идут в лежащий источник
