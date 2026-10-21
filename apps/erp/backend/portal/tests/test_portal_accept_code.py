"""Акцепт КП в портале — только одноразовым кодом (FIX-02, аудит P-1).

Код выпускает `crm.services.public_page.issue_acceptance_code`; портал гасит его через
`verify_code_and_accept`: TTL, лимит попыток, погашение и акцепт в одной транзакции. Мастер-кода нет.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from portal.tests.conftest import issue_test_acceptance_code
from rest_framework import status
from sales.models.acceptance import QuoteAcceptanceCode

from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.public_page import MAX_CODE_ATTEMPTS


@pytest.fixture
def sent_quote(db, client_company, client_contact):
    stage, _ = DealStage.objects.get_or_create(code=DealStageCode.QUOTE_SENT, defaults={"name": "КП отправлено"})
    sent, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
    deal = Deal.objects.create(company=client_company, contact=client_contact, title="Акцепт по коду", stage=stage)
    return Quote.objects.create(
        deal=deal, version=1, status=sent, total_incl_vat=Decimal("1000000"), public_access_token=uuid.uuid4().hex
    )


def _accept(portal_client, quote, code):
    return portal_client.post(f"/api/portal/v1/quotes/{quote.id}/accept", {"code": code}, format="json")


@pytest.mark.django_db
class TestAcceptByCode:
    def test_former_master_code_is_rejected_without_an_issued_code(self, portal_client, sent_quote):
        response = _accept(portal_client, sent_quote, "2468")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["detail"] == "QUOTE_CODE_INVALID"
        sent_quote.refresh_from_db()
        assert sent_quote.status.code == QuoteStatusCode.SENT

    def test_former_master_code_does_not_bypass_an_issued_code(self, portal_client, sent_quote, client_contact):
        issue_test_acceptance_code(sent_quote, client_contact.email, contact=client_contact)

        response = _accept(portal_client, sent_quote, "2468")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["detail"] == "QUOTE_CODE_INVALID"
        row = QuoteAcceptanceCode.objects.get(quote=sent_quote)
        assert row.attempts == 1 and row.consumed_at is None

    def test_issued_code_accepts_once(self, portal_client, sent_quote, client_contact):
        code = issue_test_acceptance_code(sent_quote, client_contact.email, contact=client_contact)

        first = _accept(portal_client, sent_quote, code)
        second = _accept(portal_client, sent_quote, code)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_409_CONFLICT
        assert QuoteAcceptanceCode.objects.get(quote=sent_quote).consumed_at is not None

    def test_expired_code_is_rejected(self, portal_client, sent_quote, client_contact):
        code = issue_test_acceptance_code(sent_quote, client_contact.email, contact=client_contact)
        QuoteAcceptanceCode.objects.filter(quote=sent_quote).update(expires_at=timezone.now() - timedelta(minutes=1))

        response = _accept(portal_client, sent_quote, code)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["detail"] == "QUOTE_CODE_INVALID"

    def test_attempt_cap_locks_even_the_right_code(self, portal_client, sent_quote, client_contact):
        code = issue_test_acceptance_code(sent_quote, client_contact.email, contact=client_contact)
        for _ in range(MAX_CODE_ATTEMPTS):
            assert _accept(portal_client, sent_quote, "000000").status_code == status.HTTP_409_CONFLICT

        response = _accept(portal_client, sent_quote, code)

        assert response.status_code == status.HTTP_409_CONFLICT
        sent_quote.refresh_from_db()
        assert sent_quote.status.code == QuoteStatusCode.SENT
