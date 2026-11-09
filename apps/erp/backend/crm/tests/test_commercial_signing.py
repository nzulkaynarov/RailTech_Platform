"""Тесты регламентированного подписания официальных коммерческих документов ERP (SIGN-4, ADR-0024):
- отправка запроса `uz.railtech.erp.signing.requested.v1` через `crm.services.signing_outbound`;
- приём решения `uz.railtech.eds.signing.decided.v1` через `integration.services.eds_inbound`;
- фиксация реквизитов подписания и создание публичной проекции PortalDocumentVerification.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from integration.models import CommercialSigningRequest as Request
from integration.models import CrmUserMapping
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

SIGNED = {
    "decision": "signed",
    "signer": {"crm_user_id": 3, "full_name": "Рустам Директоров", "position": "Генеральный директор"},
    "authority_id": "11111111-1111-1111-1111-111111111111",
    "basis": "charter",
    "basis_text": "на основании Устава",
    "verification_url": "https://cabinet.railtech.uz/v/X",
    "signed_at": "2026-11-07T03:00:00Z",
    "comment": None,
    "actor": {"type": "staff", "crm_user_id": 3},
}


def _signed(kind, doc, code):
    return {
        **SIGNED,
        "object": {"kind": kind, "object_id": doc.pk, "number": doc.number, "version": None},
        "verification_code": code,
    }


def _pending(kind, doc, user=None):
    from crm.services.signing_outbound import fingerprint

    return Request.objects.create(
        kind=kind, object_id=doc.pk, number=doc.number, fingerprint=fingerprint(kind, doc), requested_by=user
    )


def _seller(seller_company, email):  # noqa: F811
    user = _make_user(email)
    _make_member(user, seller_company, is_primary=True)
    CrmUserMapping.objects.create(crm_user_id=user.pk + 5000, user=user)
    return user


def _contract(deal, quote):  # noqa: F811
    return Contract.objects.create(
        deal=deal,
        quote=quote,
        number="ДОГ-2026/01",
        status=ContractStatus.objects.get(code="DRAFT"),
        total_amount=Decimal("100000.00"),
    )


@pytest.mark.django_db
def test_request_publishes_event_with_the_mapped_crm_user(lookups, deal, seller_company):  # noqa: F811
    from crm.services.signing_outbound import SIGNING_REQUESTED, request_commercial_signing

    seller = _seller(seller_company, "signer_test@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))

    with patch("crm.services.signing_outbound.get_bus") as mock_get_bus:
        mock_get_bus.return_value = MagicMock()
        request_commercial_signing(kind="contract", doc=contract, user=seller)

    event_type, data = mock_get_bus.return_value.publish.call_args[0][:2]
    assert event_type == SIGNING_REQUESTED
    assert data["object"]["kind"] == "contract"
    assert data["requested_by"]["crm_user_id"] == seller.pk + 5000
    assert data["requested_signer"] is None
    assert Request.objects.get(object_id=contract.pk).status == "pending"


@pytest.mark.django_db
def test_user_without_crm_mapping_is_refused(lookups, deal, seller_company):  # noqa: F811
    from crm.services.signing_outbound import SigningRequestError, request_commercial_signing

    seller = _make_user("no_mapping@seller.test")
    _make_member(seller, seller_company, is_primary=True)
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))

    with pytest.raises(SigningRequestError) as err:
        request_commercial_signing(kind="contract", doc=contract, user=seller)
    assert err.value.code == "NO_CRM_USER"


@pytest.mark.django_db
def test_second_request_for_the_same_edition_is_refused(lookups, deal, seller_company):  # noqa: F811
    from crm.services.signing_outbound import SigningRequestError, request_commercial_signing

    seller = _seller(seller_company, "twice@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    with patch("crm.services.signing_outbound.get_bus", return_value=MagicMock()):
        request_commercial_signing(kind="contract", doc=contract, user=seller)
        with pytest.raises(SigningRequestError) as err:
            request_commercial_signing(kind="contract", doc=contract, user=seller)
    assert err.value.code == "ALREADY_REQUESTED"


@pytest.mark.django_db
def test_signed_document_cannot_be_sent_again(lookups, deal, seller_company):  # noqa: F811
    from crm.services.signing_outbound import SigningRequestError, request_commercial_signing

    seller = _seller(seller_company, "resign@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    contract.verification_code = "ABCDEF1234"
    contract.save(update_fields=["verification_code"])
    with pytest.raises(SigningRequestError) as err:
        request_commercial_signing(kind="contract", doc=contract, user=seller)
    assert err.value.code == "ALREADY_SIGNED"


@pytest.mark.django_db
def test_signature_is_applied_and_projection_written(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    seller = _seller(seller_company, "contract_signer@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    request = _pending("contract", contract, seller)

    with patch("crm.services.contracts._render_contract_pdf") as mock_pdf:
        outcome = apply_signing_decided(_signed("contract", contract, "DOG7890123"))
    assert (outcome.applied, outcome.reason) == (True, "contract_signed")
    assert mock_pdf.called

    contract.refresh_from_db()
    request.refresh_from_db()
    assert contract.verification_code == "DOG7890123"
    assert contract.manager_signed_at is not None
    assert request.status == "signed"
    assert PortalDocumentVerification.objects.get(code="DOG7890123").status == "valid"


@pytest.mark.django_db
def test_changed_document_is_not_signed(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    seller = _seller(seller_company, "changed@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    request = _pending("contract", contract, seller)
    contract.total_amount = Decimal("999999.00")
    contract.save(update_fields=["total_amount", "updated_at"])

    outcome = apply_signing_decided(_signed("contract", contract, "CHANGED123"))

    assert outcome.reason == "stale"
    contract.refresh_from_db()
    request.refresh_from_db()
    assert contract.verification_code == ""
    assert request.status == "stale"
    assert not PortalDocumentVerification.objects.filter(code="CHANGED123").exists()


@pytest.mark.django_db
def test_decision_without_an_open_request_changes_nothing(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    seller = _seller(seller_company, "none@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))

    outcome = apply_signing_decided(_signed("contract", contract, "NOREQUEST1"))

    assert (outcome.applied, outcome.reason) == (False, "no_pending_request")
    assert not PortalDocumentVerification.objects.filter(code="NOREQUEST1").exists()


@pytest.mark.django_db
def test_rejection_is_recorded_and_the_author_is_told(lookups, deal, seller_company):  # noqa: F811
    from integration.services.eds_inbound import apply_signing_decided

    from notifications.models import Notification

    seller = _seller(seller_company, "rejected@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    request = _pending("contract", contract, seller)

    outcome = apply_signing_decided(
        {
            "object": {"kind": "contract", "object_id": contract.pk, "number": contract.number, "version": None},
            "decision": "rejected",
            "comment": "Сумма превышает лимит",
            "actor": {"type": "system"},
        }
    )

    assert outcome.reason == "rejected"
    request.refresh_from_db()
    assert (request.status, request.comment) == ("rejected", "Сумма превышает лимит")
    assert Notification.objects.filter(user=seller, message="Сумма превышает лимит").exists()


@pytest.mark.django_db
def test_signed_draft_contract_is_no_longer_a_project(lookups, deal, seller_company):  # noqa: F811
    from crm.services.documents.draft import contract_is_draft

    seller = _seller(seller_company, "draft@seller.test")
    contract = _contract(deal, _sent_quote(deal, prepared_by=seller))
    assert contract_is_draft(contract) is True
    contract.verification_code = "ABCDEF1234"
    assert contract_is_draft(contract) is False
