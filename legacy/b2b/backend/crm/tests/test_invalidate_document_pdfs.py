"""invalidate_document_pdfs management command — clears cached pdf_file so documents re-render
with the current template. Idempotent; dry-run changes nothing; filters by type/date/sent-only."""

from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Company
from crm.models import Deal, DealStage, Quote, QuoteStatus


@pytest.fixture
def sent_and_draft_quotes(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 40})
    buyer = Company.objects.create(name="Buyer", inn="7700000010")
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="T")

    def _quote(status_code, version):
        quote = Quote.objects.create(deal=deal, version=version, status=QuoteStatus.objects.get(code=status_code))
        quote.pdf_file.save(f"kp_{status_code}.pdf", ContentFile(b"%PDF-1.4 cached old template"), save=True)
        return quote

    return _quote("SENT", 1), _quote("DRAFT", 2)


def _run(**opts):
    out = StringIO()
    call_command("invalidate_document_pdfs", stdout=out, **opts)
    return out.getvalue()


@pytest.mark.django_db
def test_clears_cached_pdf(sent_and_draft_quotes):
    sent, draft = sent_and_draft_quotes
    assert sent.pdf_file and draft.pdf_file
    _run(type="quote")
    sent.refresh_from_db()
    draft.refresh_from_db()
    assert not sent.pdf_file
    assert not draft.pdf_file


@pytest.mark.django_db
def test_dry_run_changes_nothing(sent_and_draft_quotes):
    sent, _ = sent_and_draft_quotes
    output = _run(type="quote", dry_run=True)
    sent.refresh_from_db()
    assert sent.pdf_file  # still cached
    assert "dry-run" in output


@pytest.mark.django_db
def test_sent_only_skips_drafts(sent_and_draft_quotes):
    sent, draft = sent_and_draft_quotes
    _run(type="quote", sent_only=True)
    sent.refresh_from_db()
    draft.refresh_from_db()
    assert not sent.pdf_file  # SENT cleared
    assert draft.pdf_file  # DRAFT untouched


@pytest.mark.django_db
def test_idempotent_rerun(sent_and_draft_quotes):
    _run(type="quote")
    # second run: nothing left to clear, must not error
    output = _run(type="quote")
    assert "cleared 0" in output


@pytest.mark.django_db
def test_since_filter_excludes_older(sent_and_draft_quotes):
    sent, _ = sent_and_draft_quotes
    _run(type="quote", since="2999-01-01")  # future date → nothing matches
    sent.refresh_from_db()
    assert sent.pdf_file  # untouched


def test_id_without_type_errors():
    with pytest.raises(CommandError):
        call_command("invalidate_document_pdfs", id=1)
