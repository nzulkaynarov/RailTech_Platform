"""SIGN-1 (ADR-0024 п. 4): «ПРОЕКТ» на любом невыпущенном документе на бланке — единый механизм ERP.

КП до заморозки, договор / счёт / акт в DRAFT и документ-черновик печатаются с диагональным знаком на каждой странице,
«без номера» вместо номера и даты и надписью в колонтитуле; выпущенные — без знака, с номером, как прежде. Кэш PDF
(`pdf_file`) проекта несёт `-draft` в имени: проект без метки и метка на выпущенном не отдаются — идёт перерисовка.

Шаблоны рендерятся напрямую; WeasyPrint подменён записью HTML (пикселей тут нет — снимки образцов в docs/screens/SIGN-1).
Self-contained lookup seeding (CI runs --nomigrations).
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    DocumentTemplate,
    DocumentTemplateKind,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.services.documents import draft_context, pdf_is_stale, remember_pdf_state

MARK = '<div class="draft-watermark">'
NO_NUMBER = 'class="doc-no-draft"'  # «без номера» вместо номера и даты
FOOTER = "Проект — не является официальным документом"
RENDER_DELAY = "crm.tasks.render_document_pdf.delay"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()  # записи `pdf-draft-state:*` от других тестов с теми же id
    yield
    cache.clear()


class _FakeHTML:
    """Подмена `weasyprint.HTML`: запоминает HTML, «PDF» — заглушка."""

    last: str = ""

    def __init__(self, string: str = "", **_: object) -> None:
        type(self).last = string

    def write_pdf(self, target) -> None:
        target.write(b"%PDF-1.7 stub")


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 10})
    for code in ("DRAFT", "PENDING_CLIENT"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
        GeneratedDocumentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DocumentTemplateKind.objects.get_or_create(code="LETTER", defaults={"name": "Письмо", "sort_order": 10})

    buyer = Company.objects.create(name="Buyer LLC", inn="7700000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller LLC", inn="3000000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="s@sign1.test", username="s@sign1.test", password="x", is_active=True)
    CompanyMember.objects.create(
        user=user, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(title="SIGN-1", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        prepared_by=user,
        seller_company=seller,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    return {"deal": deal, "quote": quote, "buyer": buyer, "seller": seller, "user": user}


def _contract(world, status: str, **extra) -> Contract:
    return Contract.objects.create(
        deal=world["deal"],
        quote=world["quote"],
        number="CT-SIGN1-0001",
        status=ContractStatus.objects.get(code=status),
        total_amount=Decimal("112"),
        **extra,
    )


def _invoice(world, status: str, **extra) -> Invoice:
    return Invoice.objects.create(
        deal=world["deal"],
        contract=_contract(world, "PENDING_CLIENT"),
        number="INV-SIGN1-0001",
        status=InvoiceStatus.objects.get(code=status),
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
        **extra,
    )


def _act(world, status: str, **extra) -> Act:
    invoice = _invoice(world, "ISSUED")
    return Act.objects.create(
        deal=world["deal"],
        contract=invoice.contract,
        invoice=invoice,
        number="ACT-SIGN1-0001",
        status=ActStatus.objects.get(code=status),
        total_amount=Decimal("112"),
        issued_at=timezone.localdate(),
        **extra,
    )


def _generated(world, status: str) -> GeneratedDocument:
    template = DocumentTemplate.objects.create(
        company=world["seller"], name="Письмо", kind=DocumentTemplateKind.objects.get(code="LETTER")
    )
    return GeneratedDocument.objects.create(
        company=world["seller"],
        deal=world["deal"],
        template=template,
        number="DOC-SIGN1-0001",
        title="Письмо",
        rendered_html="<p>Текст письма.</p>",
        status=GeneratedDocumentStatus.objects.get(code=status),
    )


def _render(fn, obj) -> str:
    """Вызвать `_render_*_pdf` с подменой WeasyPrint: HTML, который ушёл в рендер."""
    with patch("weasyprint.HTML", _FakeHTML):
        fn(obj)
    obj.refresh_from_db()
    assert obj.pdf_file
    return _FakeHTML.last


def _contract_renderer():
    from crm.services.contracts import _render_contract_pdf

    return _render_contract_pdf


def _invoice_renderer():
    from crm.services.billing import _render_invoice_pdf

    return _render_invoice_pdf


def _act_renderer():
    from crm.services.billing import _render_act_pdf

    return _render_act_pdf


def _generated_renderer():
    from crm.services.generated_documents import _render_generated_pdf

    return _render_generated_pdf


# (фабрика документа, статус проекта, статус выпуска, рендер, свой номер)
CASES = {
    "contract": (_contract, "DRAFT", "PENDING_CLIENT", _contract_renderer, "CT-SIGN1-0001"),
    "invoice": (_invoice, "DRAFT", "ISSUED", _invoice_renderer, "INV-SIGN1-0001"),
    "act": (_act, "DRAFT", "ISSUED", _act_renderer, "ACT-SIGN1-0001"),
    "generated": (_generated, "DRAFT", "ISSUED", _generated_renderer, "DOC-SIGN1-0001"),
}


@pytest.mark.django_db
@pytest.mark.parametrize("kind", list(CASES))
def test_draft_document_renders_with_mark_and_without_number(world, kind):
    make, draft_status, _, renderer, number = CASES[kind]
    doc = make(world, draft_status)
    html = _render(renderer(), doc)
    assert MARK in html and "ПРОЕКТ" in html
    assert FOOTER in html  # колонтитул @page каждой страницы
    assert NO_NUMBER in html and "без номера" in html
    assert ".seal { display: none; }" in html, "печать («М.П.») в проекте скрыта"
    assert number not in html, "номер проекта не печатается"
    assert not pdf_is_stale(kind, doc.pk, doc.pdf_file, True), "запомнено: построен проект"
    assert pdf_is_stale(kind, doc.pk, doc.pdf_file, False)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", list(CASES))
def test_issued_document_is_unchanged(world, kind):
    make, _, issued_status, renderer, number = CASES[kind]
    doc = make(world, issued_status)
    html = _render(renderer(), doc)
    assert MARK not in html and FOOTER not in html and NO_NUMBER not in html
    assert number in html, "номер выпущенного на месте"
    assert ".seal { display: none; }" not in html
    assert not pdf_is_stale(kind, doc.pk, doc.pdf_file, False)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["contract", "invoice", "act"])
def test_templated_body_gets_no_number_in_draft(world, kind):
    """Шаблон компании: `{{doc.number}}` и `{{doc.date}}` в проекте — «без номера» и пустая дата «__» ________ 20__."""
    make, draft_status, issued_status, renderer, number = CASES[kind]
    body = "<p>Документ № {{doc.number}} от {{doc.date}}</p>"
    draft = make(world, draft_status, frozen_template_body=body)
    html = _render(renderer(), draft)
    assert "Документ № без номера от «__» ________ 20__" in html and number not in html
    Act.objects.all().delete()
    Invoice.objects.all().delete()
    Contract.objects.all().delete()  # номера уникальны: выпущенный — с тем же номером
    issued = make(world, issued_status, frozen_template_body=body)
    html = _render(renderer(), issued)
    assert number in html and "Документ № без номера" not in html


@pytest.mark.django_db
def test_invoice_payment_purpose_has_no_number_in_draft(world):
    draft = _invoice(world, "DRAFT")
    html = _render(_invoice_renderer(), draft)
    assert "Оплата по счёту" in html and "Оплата по счёту № " not in html


@pytest.mark.django_db
def test_quote_uses_the_common_mark_until_frozen(world):
    """КП: до заморозки — общий знак с «не является офертой», без номера и даты; замороженное — без знака."""
    quote = world["quote"]
    quote.number = "КП-SIGN1-0001"
    quote.frozen_at = None
    quote.save(update_fields=["number", "frozen_at"])
    from crm.services import QuoteLifecycleService

    with (
        patch("weasyprint.HTML", _FakeHTML),
        patch("crm.services.quotes.lifecycle.assert_renderable", return_value=world["seller"]),
    ):
        QuoteLifecycleService.generate_pdf(quote.pk)
    html = _FakeHTML.last
    assert MARK in html and "не является офертой" in html and FOOTER in html
    assert "КП-SIGN1-0001" not in html and NO_NUMBER in html
    quote.refresh_from_db()
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])
    with (
        patch("weasyprint.HTML", _FakeHTML),
        patch("crm.services.quotes.lifecycle.assert_renderable", return_value=world["seller"]),
    ):
        QuoteLifecycleService.generate_pdf(quote.pk)
    assert MARK not in _FakeHTML.last and "КП-SIGN1-0001" in _FakeHTML.last


@pytest.mark.django_db
def test_template_context_is_the_single_field(world):
    """Шаблон смотрит только `document_draft`: старого `is_draft` больше нет."""
    base = {"document": _generated(world, "ISSUED"), "company": None}
    shown = render_to_string("crm/generated_document_pdf.html", {**base, **draft_context(True)})
    hidden = render_to_string("crm/generated_document_pdf.html", {**base, "is_draft": True})
    assert MARK in shown and MARK not in hidden
    assert draft_context(False) == {"document_draft": False, "document_draft_offer": False}
    assert draft_context(True, offer=True)["document_draft_offer"] is True


def test_stale_rule():
    """Проект без записи о знаке — устарел; знак на выпущенном — устарел; выпущенный без записи — как прежде."""
    file = object()  # непустой файл
    assert pdf_is_stale("contract", 1, file, True)
    assert not pdf_is_stale("contract", 1, file, False)
    remember_pdf_state("contract", 1, True)
    assert not pdf_is_stale("contract", 1, file, True)
    assert pdf_is_stale("contract", 1, file, False)
    remember_pdf_state("contract", 1, False)
    assert pdf_is_stale("contract", 1, file, True) and not pdf_is_stale("contract", 1, file, False)
    assert not pdf_is_stale("contract", 2, None, True)  # файла нет — это «нет PDF», не устаревший


@pytest.fixture
def api(world):
    client = APIClient()
    client.force_authenticate(CustomUser.objects.create_superuser(email="a@sign1.test", username="a", password="x"))
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(("kind", "route"), [("contract", "contracts"), ("invoice", "invoices"), ("act", "acts")])
def test_download_does_not_serve_a_draft_pdf_without_the_mark(world, api, kind, route):
    make, draft_status, issued_status, _, _ = CASES[kind]
    doc = make(world, draft_status)
    url = f"/api/v1/crm/{route}/{doc.pk}/download-pdf/"

    doc.pdf_file.save("old-without-mark.pdf", ContentFile(b"%PDF-1.4 old"), save=True)  # записи о знаке нет
    with patch(RENDER_DELAY) as delay:
        stale = api.get(url)
    assert stale.status_code == 202, "проект без знака не отдаётся — перерисовка"
    delay.assert_called_once_with(kind, doc.pk)

    doc.pdf_file.save("marked.pdf", ContentFile(b"%PDF-1.4 marked"), save=True)
    remember_pdf_state(kind, doc.pk, True)  # то, что делает рендер проекта
    with patch(RENDER_DELAY) as delay:
        assert api.get(url).status_code == 200
    delay.assert_not_called()

    # выпуск: метка проекта на выпущенном не отдаётся, пока выпуск не перерисован
    status_model = {"contract": ContractStatus, "invoice": InvoiceStatus, "act": ActStatus}[kind]
    doc.status = status_model.objects.get(code=issued_status)
    doc.save(update_fields=["status"])
    with patch(RENDER_DELAY) as delay:
        assert api.get(url).status_code == 202
    delay.assert_called_once_with(kind, doc.pk)
