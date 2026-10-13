"""Публичная КП на телефоне: строка позиции читается целиком, без горизонтальной прокрутки.

Клиент открывает КП по QR с телефона. До 19-08 пять колонок не помещались в 320–390 px:
прокрутка у обёртки формально была, но скроллбар на телефоне оверлейный — правый край просто
обрезался, и «Цена за ед.» с «Суммой» уезжали за границу карточки БЕЗ признака, что туда можно
доскроллить (замер: 390 px → 204 px скрыто, 320 px → 274 px). Человек читал это как обрезанный
документ и цену строки не видел.

Лечение — паттерн Qwilr Quote Block: на узком экране строка таблицы перестраивается в
подписанную строку-карточку, шапка гасится, скролл-обёртка отключается. Подписи берутся
дословно из `<th>` через `data-label`.

Тест держит ровно то, что ломается молча: у КАЖДОЙ числовой ячейки обеих таблиц есть непустая
подпись. Забыть её при добавлении колонки легко — на телефоне появится неподписанное число
рядом с другим таким же, а остальные тесты промолчат.
"""

import re
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, Contact, CustomUser
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency

_INN_SEQ = [340000000]


def _next_inn():
    _INN_SEQ[0] += 1
    return str(_INN_SEQ[0])


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="QUOTE_SENT", defaults={"name": "QUOTE_SENT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "SENT", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Sum", "symbol": "сум", "sort_order": 10})


def _rich_quote(token):
    """КП со всем, что меняет раскладку строки: раздел, заметка, срок поставки, опционалка."""
    seller_user = CustomUser.objects.create_user(
        email=f"seller_{token}@rail.uz", username=f"seller_{token}", password="pw", is_active=True
    )
    seller = Company.objects.create(name="RailTech Seller", inn=_next_inn())
    buyer = Company.objects.create(name="ACME Buyer", inn=_next_inn(), is_registered=False)
    contact = Contact.objects.create(company=buyer, name="Buyer Person", email="buyer@acme.uz")
    deal = Deal.objects.create(
        company=buyer, contact=contact, stage=DealStage.objects.get(code="QUOTE_SENT"), title="Mobile reflow"
    )
    uzs = Currency.objects.get(code="UZS")
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        number="КП-2026-00777",
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller,
        prepared_by=seller_user,
        quote_currency=uzs,
        frozen_at=timezone.now(),
        public_access_token=token,
    )
    common = {"quote": quote, "frozen_currency": uzs}
    QuoteItem.objects.create(
        display_type="SECTION", imported_raw_name="Ходовая часть", position=1, quantity=Decimal("0"), **common
    )
    QuoteItem.objects.create(
        imported_raw_name="Колёсная пара РУ1Ш-957Г",
        position=2,
        quantity=Decimal("4"),
        lead_time_days=21,
        frozen_base_price=Decimal("10000000.00"),
        margin_percent=Decimal("20.00"),
        **common,
    )
    QuoteItem.objects.create(
        display_type="NOTE", imported_raw_name="Цены на условиях DAP.", position=3, quantity=Decimal("0"), **common
    )
    QuoteItem.objects.create(
        imported_raw_name="Комплект ЗИП",
        position=4,
        is_optional=True,
        quantity=Decimal("1"),
        frozen_base_price=Decimal("5000000.00"),
        margin_percent=Decimal("15.00"),
        **common,
    )
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    quote.refresh_from_db()
    return quote


def _html(quote):
    resp = APIClient().get(
        f"/api/v1/public/quotes/{quote.public_access_token}/", HTTP_ACCEPT="text/html", SERVER_NAME="localhost"
    )
    assert resp.status_code == 200
    return resp.content.decode()


@pytest.mark.django_db
def test_mobile_breakpoint_turns_rows_into_cards(lookups):
    """На узком экране: шапка гасится, таблица перестаёт быть шире экрана, обёртка не скроллится."""
    html = _html(_rich_quote("tok_mobile_reflow_1"))
    media = re.search(r"@media \(max-width: 640px\) \{(.+?)\n    \}\n", html, re.S)
    assert media, "медиазапрос телефона пропал из страницы"
    block = media.group(1)
    assert "thead { display: none; }" in block
    assert "min-width: 0" in block  # таблица больше не распирает экран
    assert "overflow-x: visible" in block  # прокрутка выключена, а не спрятана
    assert "flex-wrap: wrap" in block  # строка перестраивается


@pytest.mark.django_db
def test_every_number_cell_is_labelled(lookups):
    """Каждое число в строке подписано — иначе цена и сумма на телефоне неразличимы."""
    html = _html(_rich_quote("tok_mobile_reflow_2"))
    rows = re.findall(r"<tr>(?:(?!</tr>).)*?</tr>", html, re.S)
    checked = 0
    for row in rows:
        if "cell-no" not in row:  # строки разделов/заметок и шапки — не строки позиций
            continue
        for cell in re.findall(r"<td class=\"(?:num|center)[^\"]*\"[^>]*>", row):
            if "cell-no" in cell:
                continue  # порядковый номер стоит рядом с названием и подписи не требует
            assert 'data-label="' in cell, f"числовая ячейка без подписи: {cell}"
            label = re.search(r'data-label="([^"]*)"', cell).group(1)
            assert label.strip(), f"пустая подпись: {cell}"
            checked += 1
    assert checked >= 4, f"проверено подписей: {checked} — таблицы позиций не нашлись"


@pytest.mark.django_db
def test_labels_match_column_headers(lookups):
    """Подписи — дословно из шапки: одна сущность называется одним словом на обеих раскладках."""
    html = _html(_rich_quote("tok_mobile_reflow_3"))
    headers = {re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)}
    labels = {m for m in re.findall(r'data-label="([^"]+)"', html)}
    assert labels, "подписи исчезли"
    assert labels <= headers, f"подписи разошлись с шапкой: {labels - headers}"


@pytest.mark.django_db
def test_dead_selectors_are_gone(lookups):
    """Мёртвый CSS (.parties/.party) удалён — он делал вид, что адаптив на странице есть."""
    html = _html(_rich_quote("tok_mobile_reflow_4"))
    assert ".parties" not in html
    assert ".party " not in html


@pytest.mark.django_db
def test_code_input_keeps_its_own_size(lookups):
    """Поле кода крупнее обычных: правило поднято до тега, иначе его перебивал input[type=text]."""
    html = _html(_rich_quote("tok_mobile_reflow_5"))
    assert "input[type=text].code-input" in html
    assert "input[type=text]:not(.code-input), textarea { font-size: 16px; }" in html
