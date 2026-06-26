"""Per-company document numbering: prefix branding, independent counters, global-unique
safety, and back-compat with the platform (company=NULL) counter.
"""

import pytest
from django.db import transaction
from django.utils import timezone

from accounts.models import Company, CompanySettings
from crm.models import DocumentSequence
from crm.services.numbering import next_document_number

pytestmark = pytest.mark.django_db


def _company(name, inn, prefix=""):
    company = Company.objects.create(name=name, inn=inn)
    if prefix:
        CompanySettings.objects.create(company=company, doc_number_prefix=prefix)
    return company


def test_prefixed_company_mints_branded_number():
    year = timezone.now().year
    acme = _company("ACME", "4000000001", prefix="ACME")
    with transaction.atomic():
        number = next_document_number("CT", "КП", company=acme)
    assert number == f"ACME-КП-{year}-00001"
    assert DocumentSequence.objects.get(company=acme, doc_type="CT", year=year).last_value == 1


def test_two_companies_have_independent_counters_no_collision():
    year = timezone.now().year
    acme = _company("ACME", "4000000002", prefix="ACME")
    beta = _company("BETA", "4000000003", prefix="BETA")
    with transaction.atomic():
        a1 = next_document_number("CT", "CT", company=acme)
        a2 = next_document_number("CT", "CT", company=acme)
        b1 = next_document_number("CT", "CT", company=beta)
    # Each company has its OWN 00001 — branded distinct by prefix, so the global
    # Contract.number unique constraint is never violated.
    assert a1 == f"ACME-CT-{year}-00001"
    assert a2 == f"ACME-CT-{year}-00002"
    assert b1 == f"BETA-CT-{year}-00001"
    assert a1 != b1
    assert DocumentSequence.objects.get(company=acme, doc_type="CT", year=year).last_value == 2
    assert DocumentSequence.objects.get(company=beta, doc_type="CT", year=year).last_value == 1


def test_company_none_keeps_platform_format():
    year = timezone.now().year
    with transaction.atomic():
        number = next_document_number("INV", "INV", company=None)
    assert number == f"INV-{year}-00001"
    assert DocumentSequence.objects.get(company__isnull=True, doc_type="INV", year=year).last_value == 1


def test_prefixless_company_falls_back_to_platform_counter():
    """A company WITHOUT a prefix shares the single platform (company=NULL) counter,
    so prefix-less companies can never collide on the global `{label}-{year}-NNNNN`."""
    year = timezone.now().year
    plain = _company("Plain", "4000000004")  # no prefix
    with transaction.atomic():
        platform_first = next_document_number("INV", "INV", company=None)
        plain_next = next_document_number("INV", "INV", company=plain)
    assert platform_first == f"INV-{year}-00001"
    assert plain_next == f"INV-{year}-00002"  # continues the SAME platform sequence
    # No per-company row was created for the prefix-less company.
    assert not DocumentSequence.objects.filter(company=plain).exists()


def test_two_prefixless_companies_do_not_collide_on_global_number():
    """Regression: two companies minting the same doc_type/year must NOT produce the same
    global number. Without a prefix both route to the shared platform counter → distinct."""
    year = timezone.now().year
    one = _company("One", "4000000005")
    two = _company("Two", "4000000006")
    with transaction.atomic():
        n1 = next_document_number("CT", "CT", company=one)
        n2 = next_document_number("CT", "CT", company=two)
    assert n1 == f"CT-{year}-00001"
    assert n2 == f"CT-{year}-00002"
    assert n1 != n2


def test_sequential_mint_increments_race_smoke():
    year = timezone.now().year
    acme = _company("ACME", "4000000007", prefix="ACME")
    minted = []
    for _ in range(5):
        with transaction.atomic():
            minted.append(next_document_number("ACT", "ACT", company=acme))
    assert minted == [f"ACME-ACT-{year}-{i:05d}" for i in range(1, 6)]
    assert len(set(minted)) == 5  # all distinct, gap-free
    assert DocumentSequence.objects.get(company=acme, doc_type="ACT", year=year).last_value == 5


def test_legacy_null_company_row_unaffected_by_per_company_minting():
    """Backfilled legacy rows live at company=NULL; minting for a prefixed company must
    not touch them."""
    year = timezone.now().year
    legacy = DocumentSequence.objects.create(company=None, doc_type="CT", year=year, last_value=42)
    acme = _company("ACME", "4000000008", prefix="ACME")
    with transaction.atomic():
        next_document_number("CT", "CT", company=acme)
    legacy.refresh_from_db()
    assert legacy.last_value == 42  # untouched
