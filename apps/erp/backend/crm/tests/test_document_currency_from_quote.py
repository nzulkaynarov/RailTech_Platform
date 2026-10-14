"""B1 — invoice/contract currency must be the КП's PRESENTATION currency, never a line's COST one.

`Contract.total_amount` and `Invoice.subtotal_excl_vat/vat_amount/total_incl_vat` are copied
verbatim from the quote header, which the calculation engine computes and stores in
`Quote.quote_currency` (UZS by business rule). The materializers used to stamp the document
`currency` from the FIRST billable line's `frozen_currency` — the SUPPLIER cost currency, which on
imported rail equipment is routinely USD/EUR/RUB. The PDF templates print that code next to those
amounts, so a 13 349 617.98 UZS contract rendered as "13 349 617.98 USD" (~12 700× overstated) on
a legally binding document. Eight production documents shipped with the wrong label.

This suite pins BOTH materializers to the presentation currency and covers the 0063 data-repair
migration that realigns rows written by the old code.
"""

from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.core.files.base import ContentFile

from accounts.models import Company, CompanyType
from crm.constants import ContractStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Contract, ContractStatus, Deal, DealStage, Invoice, InvoiceStatus, Quote, QuoteItem, QuoteStatus
from crm.services.billing import generate_invoice_from_contract
from crm.services.contracts import generate_contract_from_quote
from master_data.models import Currency


@pytest.fixture
def lookups(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code, name in (
        (QuoteStatusCode.DRAFT, "Черновик"),
        (QuoteStatusCode.APPROVED, "Одобрено"),
    ):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code, name in (
        (ContractStatusCode.DRAFT, "Черновик"),
        (ContractStatusCode.PENDING_CLIENT, "Ожидает клиента"),
        (ContractStatusCode.SIGNED, "Подписан"),
    ):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    InvoiceStatus.objects.get_or_create(code=InvoiceStatusCode.ISSUED, defaults={"name": "Выставлен", "sort_order": 10})
    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "sort_order": 10})
    usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "sort_order": 20})
    return {"UZS": uzs, "USD": usd}


def _quote_priced_in_uzs_costed_in_usd(lookups, *, quote_currency):
    """The exact production shape: totals stored in the presentation currency, the underlying
    supplier line frozen in USD. `quote_currency=None` reproduces the legacy/unset case."""
    buyer = Company.objects.create(name="Buyer Co", inn="C100")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    deal = Deal.objects.create(title="Сделка", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.APPROVED),
        quote_currency=quote_currency,
        vat_rate=Decimal("12"),
    )
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Импортная позиция",
        quantity=1,
        frozen_base_price=Decimal("1050.00"),
        frozen_currency=lookups["USD"],  # COST currency — must NEVER label the document totals
        final_price_excl_vat=Decimal("11919301.77"),
    )
    # Pin the header totals AFTER the line exists: saving a line recalculates the quote, and what
    # matters here is the production shape — header amounts in the PRESENTATION currency (UZS)
    # over a line whose cost is frozen in USD. .update() bypasses the recalculation hook.
    Quote.objects.filter(pk=quote.pk).update(
        subtotal_excl_vat=Decimal("11919301.77"),
        vat_amount=Decimal("1430316.21"),
        total_incl_vat=Decimal("13349617.98"),
    )
    quote.refresh_from_db()
    return quote


# ── the fix ────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_contract_carries_quote_presentation_currency_not_line_cost_currency(lookups):
    quote = _quote_priced_in_uzs_costed_in_usd(lookups, quote_currency=lookups["UZS"])

    contract, err = generate_contract_from_quote(quote.id)

    assert err is None
    assert contract.total_amount == Decimal("13349617.98")
    assert contract.currency_id == lookups["UZS"].id, "contract labelled with the line COST currency"


@pytest.mark.django_db
def test_invoice_carries_quote_presentation_currency_not_line_cost_currency(lookups):
    quote = _quote_priced_in_uzs_costed_in_usd(lookups, quote_currency=lookups["UZS"])
    contract, _ = generate_contract_from_quote(quote.id)
    contract.status = ContractStatus.objects.get(code=ContractStatusCode.SIGNED)
    contract.save(update_fields=["status"])

    invoice, err = generate_invoice_from_contract(contract.id)

    assert err is None
    assert invoice.total_incl_vat == Decimal("13349617.98")
    assert invoice.currency_id == lookups["UZS"].id, "invoice labelled with the line COST currency"


@pytest.mark.django_db
def test_null_quote_currency_stays_null_on_both_documents(lookups):
    """`quote_currency` is nullable and both PDF templates render `|default:"UZS"` — the engine's
    canonical currency. So NULL is the SAFE outcome; the old code turned it into a bogus "USD"."""
    quote = _quote_priced_in_uzs_costed_in_usd(lookups, quote_currency=None)

    contract, _ = generate_contract_from_quote(quote.id)
    contract.status = ContractStatus.objects.get(code=ContractStatusCode.SIGNED)
    contract.save(update_fields=["status"])
    invoice, _ = generate_invoice_from_contract(contract.id)

    assert contract.currency_id is None
    assert invoice.currency_id is None


# ── 0063 data-repair migration ─────────────────────────────────────────────────────────
def _migration_fixer():
    from core.legacy_migration_helpers import fix_document_currencies

    return fix_document_currencies


@pytest.mark.django_db
def test_migration_relabels_mismatched_rows_and_invalidates_their_pdfs(lookups):
    """A row written by the old code (currency=USD, amounts in UZS) is relabelled from its quote,
    and its stale cached PDF is dropped so the next download re-renders (ARCH-03 lazy render).
    Amounts are NOT touched — the numbers were always correct UZS."""
    quote = _quote_priced_in_uzs_costed_in_usd(lookups, quote_currency=lookups["UZS"])
    contract, _ = generate_contract_from_quote(quote.id)
    contract.status = ContractStatus.objects.get(code=ContractStatusCode.SIGNED)
    contract.save(update_fields=["status"])
    invoice, _ = generate_invoice_from_contract(contract.id)
    # Rewind both rows to the corrupted pre-fix state, with a cached PDF on disk.
    Contract.objects.filter(pk=contract.pk).update(currency=lookups["USD"])
    Invoice.objects.filter(pk=invoice.pk).update(currency=lookups["USD"])
    contract.refresh_from_db()
    invoice.refresh_from_db()
    contract.pdf_file.save("Contract_stale.pdf", ContentFile(b"%PDF-1.4 wrong currency"), save=True)
    invoice.pdf_file.save("Invoice_stale.pdf", ContentFile(b"%PDF-1.4 wrong currency"), save=True)

    _migration_fixer()(django_apps, None)

    contract.refresh_from_db()
    invoice.refresh_from_db()
    assert contract.currency_id == lookups["UZS"].id
    assert invoice.currency_id == lookups["UZS"].id
    assert not contract.pdf_file, "stale PDF kept — it would keep rendering the wrong currency"
    assert not invoice.pdf_file
    # The repair is a RELABEL: no amount may move.
    assert contract.total_amount == Decimal("13349617.98")
    assert invoice.total_incl_vat == Decimal("13349617.98")


@pytest.mark.django_db
def test_migration_leaves_already_correct_rows_untouched(lookups):
    """Idempotency: a row whose currency already agrees with its quote is skipped entirely — in
    particular its cached PDF is NOT invalidated (no needless re-render of correct documents)."""
    quote = _quote_priced_in_uzs_costed_in_usd(lookups, quote_currency=lookups["UZS"])
    contract, _ = generate_contract_from_quote(quote.id)
    contract.pdf_file.save("Contract_ok.pdf", ContentFile(b"%PDF-1.4 correct"), save=True)
    assert contract.currency_id == lookups["UZS"].id  # written by the FIXED code

    _migration_fixer()(django_apps, None)

    contract.refresh_from_db()
    assert contract.currency_id == lookups["UZS"].id
    assert contract.pdf_file, "an already-correct document must not have its cached PDF dropped"
