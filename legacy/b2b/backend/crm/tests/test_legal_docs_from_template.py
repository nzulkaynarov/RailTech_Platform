"""Счёт и договор печатаются по ШАБЛОНУ (spec-editable-outgoing-documents, E1b) + починка акта.

Механика E1 распространена с акта на остальные юридические документы: платформенные образцы
приходят миграцией (Rule 1), структурные блоки вставляются одним плейсхолдером и собираются
сервером, формулировки D1 продолжают питать образец токенами `{{doc.contract_acceptance}}` и т.п.

Отдельно закрыт регресс E1: образец акта потерял блок подписей (акт без «М.П.» перестаёт быть
документом) и печатал платформенную оговорку вместо настроенной компанией.
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from crm.services.document_blocks import (
    company_template_for,
    render_act_body,
    render_contract_body,
    render_invoice_body,
)


def _invoice(notes: str = ""):
    contract = SimpleNamespace(number="CT-2026-00007")
    item = SimpleNamespace(
        description="Колодка тормозная",
        quantity=Decimal("2"),
        unit_price_excl_vat=Decimal("100.00"),
        line_total_excl_vat=Decimal("200.00"),
    )
    invoice = SimpleNamespace(
        number="INV-2026-00042",
        issued_at=datetime(2026, 7, 31, 12, 0),
        created_at=datetime(2026, 7, 30, 9, 0),
        total_incl_vat=Decimal("224.00"),
        vat_amount=Decimal("24.00"),
        notes=notes,
        contract=contract,
    )
    return invoice, [item]


def _contract(profile=None, valid_from=None, notes=""):
    buyer = SimpleNamespace(
        name="Покупатель LLC", inn="7700000001", legal_address="г. Ташкент", bank_account="", mfo="", phone=""
    )
    item = SimpleNamespace(
        product=None,
        imported_raw_name="Колодка тормозная",
        quantity=Decimal("2"),
        unit=None,
        final_price_excl_vat=Decimal("100.00"),
        line_total=Decimal("200.00"),
    )
    quote = SimpleNamespace(vat_rate=Decimal("12"), effective_delivery_lead_time_days=30, delivery_basis=None)
    contract = SimpleNamespace(
        number="CT-2026-00007",
        created_at=datetime(2026, 7, 31, 12, 0),
        total_amount=Decimal("224.00"),
        quote=quote,
        quote_id=1,
        valid_from=valid_from,
        valid_until=None,
        notes=notes,
        manager_signer=None,
        client_signer=None,
        deal=SimpleNamespace(company=buyer),
    )
    return contract, [item]


TOTALS = {
    "ccy": "UZS",
    "vat_rate": Decimal("12"),
    "subtotal": Decimal("200.00"),
    "vat_amount": Decimal("24.00"),
    "total": Decimal("224.00"),
}


@pytest.mark.django_db
def test_platform_samples_exist_for_invoice_and_contract_after_migrate():
    """Rule 1: заготовки приходят миграцией — на чистой базе они уже есть."""
    for kind in ("INVOICE", "CONTRACT"):
        sample = company_template_for(None, kind)
        assert sample is not None, kind
        assert sample.is_sample is True and sample.company_id is None


@pytest.mark.django_db
def test_invoice_sample_reproduces_the_code_rendered_invoice():
    """Компания без своего шаблона обязана получить прежний документ: позиции, платёжные
    реквизиты с назначением платежа и подписи руководителя и главбуха."""
    invoice, items = _invoice()
    seller = SimpleNamespace(name="ООО РельсМаш", inn="3000000001", bank_account="20208000", mfo="00014")

    body = render_invoice_body(invoice, items, TOTALS, "UZS", company_template_for(None, "INVOICE"), seller=seller)

    assert "Колодка тормозная" in body
    assert "Платёжные реквизиты" in body
    assert "Оплата по счёту № INV-2026-00042" in body and "договор № CT-2026-00007" in body
    assert "Руководитель:" in body and "Главный бухгалтер:" in body
    assert "Итого к оплате" in body


@pytest.mark.django_db
def test_invoice_notes_print_only_when_present():
    """Пустое примечание не печатает ни заголовка, ни пустой рамки."""
    sample = company_template_for(None, "INVOICE")
    without_notes, items = _invoice("")
    with_notes, _ = _invoice("Срочная поставка")

    assert "Примечание" not in render_invoice_body(without_notes, items, TOTALS, "UZS", sample)
    rendered = render_invoice_body(with_notes, items, TOTALS, "UZS", sample)
    assert "Примечание" in rendered and "Срочная поставка" in rendered


@pytest.mark.django_db
def test_contract_sample_reproduces_the_code_rendered_contract():
    """Статьи, спецификация, срок поставки и реквизиты — как печатал код-шаблон."""
    contract, items = _contract()
    seller = SimpleNamespace(name="ООО РельсМаш", inn="3000000001", legal_address="", bank_account="", mfo="", phone="")

    body = render_contract_body(contract, items, TOTALS, "UZS", company_template_for(None, "CONTRACT"), seller=seller)

    assert "1. Предмет договора" in body
    assert "Приложение № 1. Спецификация" in body and "Колодка тормозная" in body
    assert "включая НДС по ставке 12%" in body
    assert "в срок до 30 календарных дней" in body
    assert "с даты его подписания обеими Сторонами" in body
    assert "10. Реквизиты и подписи Сторон" in body
    assert "10. Особые условия" not in body, "пустые особые условия не печатаются"


@pytest.mark.django_db
def test_contract_extra_terms_shift_the_requisites_article_number():
    """«Особые условия» компании печатаются пунктом 10, реквизиты сдвигаются на 11 — без
    «дыры» в нумерации, как в код-шаблоне."""
    profile = SimpleNamespace(
        contract_extra_terms_text="Гарантия 24 месяца.",
        contract_acceptance_text="",
        contract_liability_text="",
        act_closing_text="",
        legal_name="",
        inn="",
        legal_address="",
        bank_details="",
        signatory_name="",
        signatory_position="",
    )
    contract, items = _contract()

    body = render_contract_body(
        contract, items, TOTALS, "UZS", company_template_for(None, "CONTRACT"), seller_profile=profile
    )

    assert "10. Особые условия" in body and "Гарантия 24 месяца." in body
    assert "11. Реквизиты и подписи Сторон" in body


@pytest.mark.django_db
def test_company_wording_feeds_the_platform_samples():
    """D1 → E1b: настроенные формулировки компании питают платформенный образец (spec §4)."""
    profile = SimpleNamespace(
        contract_liability_text="Неустойка 0,05% за каждый день просрочки.",
        contract_acceptance_text="",
        contract_extra_terms_text="",
        act_closing_text="Претензий нет, приёмка по ТУ-42.",
        legal_name="",
        inn="",
        legal_address="",
        bank_details="",
        signatory_name="",
        signatory_position="",
    )
    contract, items = _contract()
    body = render_contract_body(
        contract, items, TOTALS, "UZS", company_template_for(None, "CONTRACT"), seller_profile=profile
    )
    assert "Неустойка 0,05% за каждый день просрочки." in body

    act = SimpleNamespace(
        number="ACT-1",
        issued_at=datetime(2026, 7, 31),
        total_amount=Decimal("224.00"),
        deal=SimpleNamespace(company=SimpleNamespace(name="Покупатель LLC")),
        deal_id=1,
        contract=None,
        invoice=None,
    )
    act_body = render_act_body(act, None, TOTALS, "UZS", company_template_for(None, "ACT"), seller_profile=profile)
    assert "Претензий нет, приёмка по ТУ-42." in act_body


@pytest.mark.django_db
def test_act_sample_prints_signatures_again():
    """Регресс E1: акт по образцу печатался без подписей и «М.П.» — документ переставал быть
    документом. Образец обязан снова содержать блок подписей."""
    sample = company_template_for(None, "ACT")
    assert "{{doc.signatures}}" in sample.body_html
    assert "{{doc.act_closing}}" in sample.body_html

    act = SimpleNamespace(
        number="ACT-1",
        issued_at=datetime(2026, 7, 31),
        total_amount=Decimal("224.00"),
        deal=SimpleNamespace(company=SimpleNamespace(name="Покупатель LLC")),
        deal_id=1,
        contract=None,
        invoice=None,
    )
    body = render_act_body(act, None, TOTALS, "UZS", sample, seller=SimpleNamespace(name="ООО РельсМаш"))

    assert "От Поставщика:" in body and "От Покупателя:" in body
    assert "М.П." in body
    assert "ООО РельсМаш" in body and "Покупатель LLC" in body
