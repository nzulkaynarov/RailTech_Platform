"""N1 — configurable document numbering scheme.

Covers: the default scheme reproduces the historical format at ZERO visual diff (prefixed
and prefix-less); custom pattern + padding; reset never/yearly/monthly period keys;
sequential/no-gap minting inside one transaction; global-unique safety for two prefix-less
companies (shared platform counter); and pattern validation ({seq} mandatory).

Month-dependent behaviour is driven through a mocked `timezone.now`, never the wall clock.
"""

import datetime as dt
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Company, CompanySettings
from crm.models import DocumentNumberingScheme, DocumentSequence
from crm.services import numbering
from crm.services.numbering import get_company_scheme, next_document_number, set_company_scheme

pytestmark = pytest.mark.django_db


def _company(name, inn, prefix=""):
    company = Company.objects.create(name=name, inn=inn)
    if prefix:
        CompanySettings.objects.create(company=company, doc_number_prefix=prefix)
    return company


def _at(year, month=6, day=15):
    """A fixed aware datetime for mocking timezone.now()."""
    return timezone.make_aware(dt.datetime(year, month, day, 12, 0, 0))


# ── Zero-diff: default scheme reproduces the historical format ──────────────────────


def test_default_scheme_reproduces_prefix_less_format():
    year = timezone.now().year
    with transaction.atomic():
        first = next_document_number("INV", "INV")
        second = next_document_number("INV", "INV")
    assert first == f"INV-{year}-00001"
    assert second == f"INV-{year}-00002"


def test_default_scheme_reproduces_prefixed_format():
    year = timezone.now().year
    acme = _company("ACME", "6100000001", prefix="ACME")
    with transaction.atomic():
        # The {type} token now renders from the scheme's editable type_labels (default
        # KP→"КП"), so the branded historical shape is unchanged at zero config.
        number = next_document_number("KP", "КП", company=acme)
    assert number == f"ACME-КП-{year}-00001"
    with transaction.atomic():
        contract = next_document_number("CT", "CT", company=acme)
    assert contract == f"ACME-CT-{year}-00001"


def test_default_scheme_used_without_any_scheme_row():
    """Even with the platform default row deleted, the code-level DEFAULT_SCHEME applies —
    numbering never depends on a row existing (Rule 1: no write-on-read)."""
    DocumentNumberingScheme.objects.all().delete()
    year = timezone.now().year
    with transaction.atomic():
        number = next_document_number("ACT", "ACT")
    assert number == f"ACT-{year}-00001"


# ── Custom pattern + padding ────────────────────────────────────────────────────────


def test_custom_pattern_and_padding():
    year = timezone.now().year
    acme = _company("ACME", "6100000002", prefix="ACME")
    set_company_scheme(acme, pattern="{type}/{YYYY}/{seq}", padding=6)
    with transaction.atomic():
        first = next_document_number("CT", "CT", company=acme)
        second = next_document_number("CT", "CT", company=acme)
    assert first == f"CT/{year}/000001"
    assert second == f"CT/{year}/000002"


def test_custom_start_value_offsets_first_number():
    year = timezone.now().year
    acme = _company("ACME", "6100000003", prefix="ACME")
    set_company_scheme(acme, pattern="{prefix}{type}-{YYYY}-{seq}", start_value=1000)
    with transaction.atomic():
        first = next_document_number("CT", "CT", company=acme)
    # first number = start_value + 1
    assert first == f"ACME-CT-{year}-01001"


def test_two_digit_year_and_month_tokens():
    acme = _company("ACME", "6100000004", prefix="ACME")
    set_company_scheme(acme, pattern="{prefix}{type}{YY}{MM}-{seq}", padding=3)
    with mock.patch.object(timezone, "now", return_value=_at(2026, 3)):
        with transaction.atomic():
            number = next_document_number("INV", "INV", company=acme)
    assert number == "ACME-INV2603-001"


# ── Reset period ────────────────────────────────────────────────────────────────────


def test_reset_yearly_new_counter_each_year():
    acme = _company("ACME", "6100000005", prefix="ACME")
    set_company_scheme(acme, reset_period="yearly")
    with mock.patch.object(timezone, "now", return_value=_at(2025)):
        with transaction.atomic():
            n2025 = next_document_number("CT", "CT", company=acme)
    with mock.patch.object(timezone, "now", return_value=_at(2026)):
        with transaction.atomic():
            n2026 = next_document_number("CT", "CT", company=acme)
    assert n2025 == "ACME-CT-2025-00001"
    assert n2026 == "ACME-CT-2026-00001"  # counter reset for the new year


def test_reset_monthly_new_counter_each_month():
    acme = _company("ACME", "6100000006", prefix="ACME")
    set_company_scheme(acme, pattern="{prefix}{type}-{YYYY}{MM}-{seq}", reset_period="monthly")
    with mock.patch.object(timezone, "now", return_value=_at(2026, 1)):
        with transaction.atomic():
            jan1 = next_document_number("CT", "CT", company=acme)
            jan2 = next_document_number("CT", "CT", company=acme)
    with mock.patch.object(timezone, "now", return_value=_at(2026, 2)):
        with transaction.atomic():
            feb1 = next_document_number("CT", "CT", company=acme)
    assert jan1 == "ACME-CT-202601-00001"
    assert jan2 == "ACME-CT-202601-00002"
    assert feb1 == "ACME-CT-202602-00001"  # fresh counter for February
    # Distinct period keys → distinct counter rows.
    assert DocumentSequence.objects.filter(company=acme, doc_type="CT").count() == 2


def test_reset_never_single_counter_across_years():
    acme = _company("ACME", "6100000007", prefix="ACME")
    set_company_scheme(acme, pattern="{prefix}{type}-{seq}", reset_period="never")
    with mock.patch.object(timezone, "now", return_value=_at(2025)):
        with transaction.atomic():
            n2025 = next_document_number("CT", "CT", company=acme)
    with mock.patch.object(timezone, "now", return_value=_at(2026)):
        with transaction.atomic():
            n2026 = next_document_number("CT", "CT", company=acme)
    assert n2025 == "ACME-CT-00001"
    assert n2026 == "ACME-CT-00002"  # keeps counting across the year boundary
    assert DocumentSequence.objects.filter(company=acme, doc_type="CT").count() == 1
    assert DocumentSequence.objects.get(company=acme, doc_type="CT").period == "ALL"


# ── Sequential / no-gap + race smoke ────────────────────────────────────────────────


def test_sequential_no_gap_within_transaction():
    year = timezone.now().year
    acme = _company("ACME", "6100000008", prefix="ACME")
    minted = []
    with transaction.atomic():
        for _ in range(5):
            minted.append(next_document_number("ACT", "ACT", company=acme))
    assert minted == [f"ACME-ACT-{year}-{i:05d}" for i in range(1, 6)]
    assert len(set(minted)) == 5


# ── Global-unique safety (unchanged invariant) ─────────────────────────────────────


def test_two_prefixless_companies_share_platform_counter_no_collision():
    year = timezone.now().year
    one = _company("One", "6100000009")
    two = _company("Two", "6100000010")
    # Even if a prefix-less company sets a divergent scheme, it is NOT effective — it
    # shares the platform counter/scheme, so the two can never collide on the global number.
    set_company_scheme(one, pattern="{type}/{YYYY}/{seq}", reset_period="monthly")
    with transaction.atomic():
        n1 = next_document_number("CT", "CT", company=one)
        n2 = next_document_number("CT", "CT", company=two)
    assert n1 == f"CT-{year}-00001"
    assert n2 == f"CT-{year}-00002"
    assert n1 != n2
    assert not DocumentSequence.objects.filter(company=one).exists()
    assert not DocumentSequence.objects.filter(company=two).exists()


def test_prefixless_company_falls_back_to_platform_counter():
    year = timezone.now().year
    plain = _company("Plain", "6100000011")
    with transaction.atomic():
        platform_first = next_document_number("INV", "INV", company=None)
        plain_next = next_document_number("INV", "INV", company=plain)
    assert platform_first == f"INV-{year}-00001"
    assert plain_next == f"INV-{year}-00002"


# ── Editability API ─────────────────────────────────────────────────────────────────


def test_get_company_scheme_effective_spec():
    acme = _company("ACME", "6100000012", prefix="ACME")
    set_company_scheme(acme, pattern="{type}-{seq}", padding=4, reset_period="never", start_value=7)
    spec = get_company_scheme(acme)
    assert spec.pattern == "{type}-{seq}"
    assert spec.padding == 4
    assert spec.reset_period == "never"
    assert spec.start_value == 7


def test_get_company_scheme_defaults_when_no_row():
    acme = _company("ACME", "6100000013", prefix="ACME")
    spec = get_company_scheme(acme)
    assert spec == numbering.DEFAULT_SCHEME


def test_set_company_scheme_is_upsert():
    acme = _company("ACME", "6100000014", prefix="ACME")
    set_company_scheme(acme, padding=6)
    set_company_scheme(acme, padding=8)
    assert DocumentNumberingScheme.objects.filter(company=acme).count() == 1
    assert DocumentNumberingScheme.objects.get(company=acme).padding == 8


# ── Validation ──────────────────────────────────────────────────────────────────────


def test_pattern_without_seq_rejected():
    acme = _company("ACME", "6100000015", prefix="ACME")
    with pytest.raises(ValidationError):
        set_company_scheme(acme, pattern="{prefix}{type}-{YYYY}")


def test_empty_pattern_rejected():
    acme = _company("ACME", "6100000016", prefix="ACME")
    with pytest.raises(ValidationError):
        set_company_scheme(acme, pattern="   ")
