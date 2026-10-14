"""Regression: DocumentSequence must not re-issue an existing document number.

0020 created the sequence without seeding it, so on a DB with existing Contracts the
counter started at 0 and collided (`duplicate key crm_contract_number_key` 500 in prod).
0037 backfills the counter to the max existing suffix.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import transaction

from accounts.models import Company, CustomUser
from crm.models import Contract, ContractStatus, Deal, DealStage, DocumentSequence, Quote, QuoteStatus
from crm.services.numbering import next_document_number

pytestmark = pytest.mark.django_db
_MIG = importlib.import_module("crm.migrations.0037_backfill_document_sequences")


def test_backfill_corrects_behind_counter_and_prevents_collision():
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})
    cstatus = ContractStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 10})[0]
    company = Company.objects.create(name="Numbering LLC", inn="5500000099")
    user = CustomUser.objects.create_user(email="num@example.com", username="num", password="pw")
    deal = Deal.objects.create(title="N", company=company, client=user, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    # Existing contract at suffix 7, but the counter is stuck at 0 (the 0020 bug state).
    Contract.objects.create(deal=deal, quote=quote, number="CT-2026-00007", status=cstatus)
    DocumentSequence.objects.update_or_create(doc_type="CT", year=2026, defaults={"last_value": 0})

    _MIG.backfill_sequences(django_apps, None)
    assert DocumentSequence.objects.get(doc_type="CT", year=2026).last_value == 7

    with transaction.atomic():
        nxt = next_document_number("CT", "CT")
    assert nxt == "CT-2026-00008"  # no collision with the existing CT-2026-00007
    assert not Contract.objects.filter(number=nxt).exists()
