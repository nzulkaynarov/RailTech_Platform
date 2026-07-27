"""КП-письмо (владелец 27-07): КП оформляется как деловое письмо, не как договор.

ГОСТ Р 7.0.97-2016 реквизит «адресат»: справа под реквизитами бланка, ДО заголовка,
«куда» (организация) + «кому» (лицо). Двухколоночный блок «Поставщик/Покупатель» в КП
отменён (он «обязывал покупателя»); стороны остаются в договоре/инвойсе/акте. Имя
PDF-файла = номер КП из схемы нумерации продавца.
"""

from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from crm.services.documents import quote_pdf_filename


def _ctx(**over):
    ctx = {
        "quote": {
            "quote_currency": {"code": "UZS"},
            "number": "КП-2026-00007",
            "deal_id": 7,
            "version": 1,
            "created_at": None,
            "valid_until": None,
            "vat_rate": 12,
            "prepared_by": None,
        },
        "items": [],
        "company": SimpleNamespace(
            name="ООО «Тест»", inn="123", legal_address="", contact_person="Директору Иванову К. К."
        ),
        "contact": None,
        "seller": SimpleNamespace(name="ООО «Продавец»", inn="456", legal_address="", phone="", email=""),
        "seller_profile": None,
        "seller_logo_url": None,
        "is_demo": False,
    }
    ctx.update(over)
    return ctx


def test_kp_renders_addressee_before_title_not_parties():
    html = render_to_string("crm/quote_pdf.html", _ctx())
    body = html.split("</head>")[1]  # markup only — the <style> block always names classes
    assert "addressee-wrap" in body
    assert "ООО «Тест»" in body
    assert "Директору Иванову К. К." in body
    # The contract-like parties block is GONE from the КП…
    assert "<h3>Поставщик</h3>" not in body
    assert "<h3>Покупатель</h3>" not in body
    # …and the addressee prints BEFORE the document title (letter form).
    assert body.index("Директору Иванову К. К.") < body.index("Коммерческое предложение")


def test_kp_addressee_uses_offline_contact_on_solo_deal():
    html = render_to_string(
        "crm/quote_pdf.html",
        _ctx(company=None, contact=SimpleNamespace(name="Иванов К. К.", position="Директор")),
    )
    body = html.split("</head>")[1]
    assert "Директор" in body
    assert "Иванов К. К." in body


def test_kp_addressee_absent_for_companyless_draft():
    html = render_to_string("crm/quote_pdf.html", _ctx(company=None, contact=None))
    body = html.split("</head>")[1]
    assert "addressee-wrap" not in body  # калькулятор без клиента — письмо без адресата, не «—»


def test_quote_pdf_filename_uses_numbering_scheme():
    quote = SimpleNamespace(number="КП-2026-00042", deal_id=9, version=2)
    assert quote_pdf_filename(quote) == "КП-2026-00042_v2.pdf"
    # Unsafe characters collapse; the number stays recognizable.
    quote_slash = SimpleNamespace(number="RFQ/0726 RT №1", deal_id=9, version=1)
    assert quote_pdf_filename(quote_slash) == "RFQ_0726_RT_1_v1.pdf"
    # A draft with no number degrades to the legacy deal-scoped name.
    draft = SimpleNamespace(number="", deal_id=9, version=3)
    assert quote_pdf_filename(draft) == "KP_9_v3.pdf"
