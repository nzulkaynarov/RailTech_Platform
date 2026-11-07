"""Тесты регламентированного подписания официальных коммерческих документов ERP (SIGN-4, ADR-0024):
- отправка запроса `uz.railtech.erp.signing.requested.v1` через `crm.services.signing_outbound`;
- приём решения `uz.railtech.eds.signing.decided.v1` через `integration.services.eds_inbound`;
- фиксация реквизитов подписания и создание публичной проекции PortalDocumentVerification.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from portal.models import PortalDocumentVerification

from crm.models import Contract, ContractStatus
from crm.tests.test_permission_guards import (  # noqa: F401 — фикстуры
    _make_member,
    _make_user,
    _sent_quote,
    buyer_company,
    deal,
    lookups,
    seller_company,
)


@pytest.mark.django_db
def test_request_commercial_signing_publishes_event(lookups, deal, seller_company):  # noqa: F811
    from crm.services.signing_outbound import SIGNING_REQUESTED, request_commercial_signing

    seller = _make_user("signer_test@seller.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)

    with patch("crm.services.signing_outbound.get_bus") as mock_get_bus:
        mock_bus = MagicMock()
        mock_get_bus.return_value = mock_bus

        request_commercial_signing(
            kind="quote",
            doc=quote,
            user=seller,
        )

        assert mock_bus.publish.called
        call_args = mock_bus.publish.call_args
        event_type, data = call_args[0][0], call_args[0][1]
        assert event_type == SIGNING_REQUESTED
        assert data["object"]["kind"] == "quote"
        assert data["object"]["object_id"] == quote.pk
        assert data["requested_by"]["crm_user_id"] == seller.pk
        assert data["actor"]["type"] == "staff"


@pytest.mark.django_db
def test_apply_signing_decided_quote(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    seller = _make_user("quote_signer@seller.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)

    signing_data = {
        "object": {
            "kind": "quote",
            "object_id": quote.pk,
            "number": quote.number or "КП-001",
            "version": quote.version,
        },
        "decision": "signed",
        "signer": {
            "crm_user_id": 3,
            "full_name": "Рустам Директоров",
            "position": "Генеральный директор",
        },
        "authority_id": "11111111-1111-1111-1111-111111111111",
        "basis": "charter",
        "basis_text": "на основании Устава",
        "verification_code": "CODE123456",
        "verification_url": "https://cabinet.railtech.uz/v/CODE123456",
        "signed_at": "2026-11-07T03:00:00Z",
        "comment": None,
        "actor": {"type": "staff", "crm_user_id": 3},
    }

    with patch("crm.services.quotes.lifecycle.QuoteLifecycleService.generate_pdf") as mock_pdf:
        outcome = apply_signing_decided(signing_data)
        assert outcome.applied is True
        assert outcome.reason == "quote_signed"
        assert mock_pdf.called

    quote.refresh_from_db()
    assert quote.verification_code == "CODE123456"
    assert quote.signatory_name == "Рустам Директоров"
    assert quote.signatory_position == "Генеральный директор"
    assert quote.signatory_basis == "charter"
    assert quote.signed_at is not None

    verification = PortalDocumentVerification.objects.filter(code="CODE123456").first()
    assert verification is not None
    assert verification.kind == "quote"
    assert verification.signatory_name == "Рустам Директоров"
    assert verification.status == "valid"


@pytest.mark.django_db
def test_apply_signing_decided_contract(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    seller = _make_user("contract_signer@seller.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)

    status_draft = ContractStatus.objects.get(code="DRAFT")
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="ДОГ-2026/01",
        status=status_draft,
        total_amount=Decimal("100000.00"),
    )

    signing_data = {
        "object": {
            "kind": "contract",
            "object_id": contract.pk,
            "number": contract.number,
            "version": None,
        },
        "decision": "signed",
        "signer": {
            "crm_user_id": 3,
            "full_name": "Рустам Директоров",
            "position": "Генеральный директор",
        },
        "authority_id": "11111111-1111-1111-1111-111111111111",
        "basis": "charter",
        "basis_text": "на основании Устава",
        "verification_code": "DOG7890123",
        "verification_url": "https://cabinet.railtech.uz/v/DOG7890123",
        "signed_at": "2026-11-07T03:00:00Z",
        "comment": None,
        "actor": {"type": "staff", "crm_user_id": 3},
    }

    with patch("crm.services.contracts._render_contract_pdf") as mock_pdf:
        outcome = apply_signing_decided(signing_data)
        assert outcome.applied is True
        assert outcome.reason == "contract_signed"
        assert mock_pdf.called

    contract.refresh_from_db()
    assert contract.verification_code == "DOG7890123"
    assert contract.signatory_name == "Рустам Директоров"
    assert contract.signed_at is not None
    assert contract.manager_signed_at is not None


@pytest.mark.django_db
def test_apply_signing_decided_rejected(lookups, deal):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    signing_data = {
        "object": {
            "kind": "contract",
            "object_id": 9999,
            "number": "ДОГ-FAKE",
            "version": None,
        },
        "decision": "rejected",
        "comment": "Сумма превышает лимит по доверенности",
        "actor": {"type": "system"},
    }

    outcome = apply_signing_decided(signing_data)
    assert outcome.applied is True
    assert outcome.reason == "rejected"
