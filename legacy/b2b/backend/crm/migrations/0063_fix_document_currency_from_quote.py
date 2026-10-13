"""Data repair (B1): invoice/contract `currency` held the per-line COST currency.

`generate_contract_from_quote` / `generate_invoice_from_contract` used to stamp the document
currency from the FIRST billable line's `frozen_currency` — the SUPPLIER cost currency (often
USD/EUR/RUB for imported rail equipment). But `total_amount` / `subtotal_excl_vat` / `vat_amount`
/ `total_incl_vat` are copied verbatim from the quote header, which the calculation engine
computes and stores in the PRESENTATION currency (`Quote.quote_currency`, UZS by business rule).
The PDF templates print that currency code next to those amounts, so a contract worth
68 565 766 523.59 UZS rendered as "$68.5 billion" on a legal document.

The code is fixed to use `quote.quote_currency`; this migration realigns the rows already written
by the old code, deriving each document's currency from its linked quote exactly as the fixed
code now does.

!! AMOUNTS ARE NOT TOUCHED, CONVERTED OR RECALCULATED !!
The stored numbers were ALWAYS correct UZS values — only the label was wrong. A future reader
must NOT "helpfully" add an FX conversion here: multiplying or dividing any amount in this
migration would corrupt correct data. The fix is a relabel, nothing else.

NULL is a legitimate target value: `quote_currency` is nullable and both PDF templates render
`|default:"UZS"`, which is the engine's canonical currency — so NULL and an explicit UZS row both
render correctly.

Cached PDFs: the affected documents already have a rendered `pdf_file` on disk showing the wrong
code, and the download endpoints only re-render when `pdf_file` is EMPTY (`_stream_or_render_pdf`
→ 202 + enqueue, ARCH-03). Corrected rows therefore get their `pdf_file` field CLEARED so the next
download regenerates the document from the fixed data. The old file is left on storage (orphaned,
not deleted) — this migration performs no destructive file operations.

Idempotent: rows whose currency already agrees with the quote are skipped entirely (no write, no
PDF invalidation). Reverse is a documented no-op — the previous values were wrong and restoring
them would re-corrupt legal documents.
"""

from django.db import migrations


def _fix_document_currencies(apps, schema_editor):
    Contract = apps.get_model("crm", "Contract")
    Invoice = apps.get_model("crm", "Invoice")

    # Contract → quote directly.
    for contract in Contract.objects.select_related("quote").exclude(quote__isnull=True).iterator():
        correct_currency_id = contract.quote.quote_currency_id
        if contract.currency_id == correct_currency_id:
            continue  # already correct — leave the row (and its cached PDF) alone
        contract.currency_id = correct_currency_id
        contract.pdf_file = ""  # invalidate the stale cached render (lazy re-render on download)
        contract.save(update_fields=["currency", "pdf_file"])

    # Invoice → contract → quote (an invoice is always materialized from a signed contract;
    # a manual invoice without one has no quote to derive from and is left untouched).
    for invoice in (
        Invoice.objects.select_related("contract__quote")
        .exclude(contract__isnull=True)
        .exclude(contract__quote__isnull=True)
        .iterator()
    ):
        correct_currency_id = invoice.contract.quote.quote_currency_id
        if invoice.currency_id == correct_currency_id:
            continue
        invoice.currency_id = correct_currency_id
        invoice.pdf_file = ""
        invoice.save(update_fields=["currency", "pdf_file"])


def _reverse_noop(apps, schema_editor):
    """No-op by design: the pre-migration values were the WRONG (cost) currency on legal
    documents. Restoring them would re-introduce the misrepresentation, so reversing this
    migration deliberately leaves the corrected data in place."""


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0062_alter_quoteitem_options_and_more"),
    ]

    operations = [
        migrations.RunPython(_fix_document_currencies, _reverse_noop),
    ]
