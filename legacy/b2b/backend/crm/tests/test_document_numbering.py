"""Race-safe document numbering (replaces count()+1 → duplicate-number 500)."""

import pytest
from django.db import transaction
from django.utils import timezone

from crm.models import DocumentSequence
from crm.services.numbering import next_document_number


@pytest.mark.django_db
def test_numbers_are_sequential_and_formatted():
    year = timezone.now().year
    with transaction.atomic():
        first = next_document_number("INV", "INV")
        second = next_document_number("INV", "INV")
        third = next_document_number("INV", "INV")
    assert [first, second, third] == [f"INV-{year}-00001", f"INV-{year}-00002", f"INV-{year}-00003"]
    assert DocumentSequence.objects.get(doc_type="INV", year=year).last_value == 3


@pytest.mark.django_db
def test_counters_are_independent_per_doc_type():
    year = timezone.now().year
    with transaction.atomic():
        inv = next_document_number("INV", "INV")
        act = next_document_number("ACT", "ACT")
        ct = next_document_number("CT", "CT")
    assert inv == f"INV-{year}-00001"
    assert act == f"ACT-{year}-00001"
    assert ct == f"CT-{year}-00001"
    assert DocumentSequence.objects.count() == 3


@pytest.mark.django_db
def test_sequence_row_reused_not_recreated():
    """A second call for the same (doc_type, year) reuses the one locked row —
    no duplicate rows, which is what makes the number gap-free under concurrency."""
    year = timezone.now().year
    with transaction.atomic():
        next_document_number("INV", "INV")
    with transaction.atomic():
        next_document_number("INV", "INV")
    assert DocumentSequence.objects.filter(doc_type="INV", year=year).count() == 1
