"""F2 «Доставка письма» (block II) — public link, email delivery, buyer read-only visibility.

Covers: the anonymous public document view (ISSUED-only gate: 404 on DRAFT/CANCELLED, 410 on
revoked/expired); the send-email action (ISSUED + ownership gate); the issue→counterparty
Notification (and none on a solo deal); the widened registry queryset (buyer sees a received ISSUED
document read-only, cannot cancel it, a member of another client company or an outsider never
sees it); the ?deal= filter. The seller is the own company (single seller, M1-ERP-02 wave 3).

Self-contained lookup seeding (CI runs --nomigrations)."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm import services as crm_services
from crm.models import Deal, DealStage, DocumentTemplateKind, GeneratedDocumentStatus
from notifications.models import Notification, NotificationType


@pytest.fixture
def lookups(db):
    for code, name in (("LETTER", "Письмо"), ("CUSTOM", "Произвольный")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "CANCELLED"):
        GeneratedDocumentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _template(company, user, body="<p>{{deal.title}}</p>"):
    return crm_services.create_template(company, user, name="Письмо", kind_code="LETTER", body_html=body)


@pytest.fixture
def world(lookups):
    """Own-company staff issue a document on a buyer-owned deal; a buyer of ANOTHER client company
    has nothing to do with it."""
    seller_co = _company("Own Co", "S1", "SUPPLIER")
    seller_user = _member(seller_co, "seller@doc.test", can_sell=True)

    buyer_co = _company("Buyer Co", "B1", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@doc.test", can_buy=True)

    other_co = _company("Other Client", "O1", "CLIENT")
    other_user = _member(other_co, "other@doc.test", can_buy=True)

    deal = Deal.objects.create(company=buyer_co, stage=DealStage.objects.get(code="DRAFT"), title="Поставка")

    return {
        "seller_co": seller_co,
        "seller_user": seller_user,
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "other_user": other_user,
        "deal": deal,
    }


def _issue(world, deal=None):
    seller_co, seller_user = world["seller_co"], world["seller_user"]
    deal = deal if deal is not None else world["deal"]
    document, err = crm_services.generate_document(
        seller_co, seller_user, template=_template(seller_co, seller_user), deal=deal
    )
    assert err is None
    issued, err = crm_services.issue_document(document, seller_user)
    assert err is None
    return issued


# ── II-1: public link on issue + anonymous view gate ─────────────────────────


def test_issue_mints_public_token_and_expiry(world):
    document = _issue(world)
    assert document.public_access_token
    assert document.public_token_expires_at is not None
    assert document.public_token_revoked is False


def test_public_view_serves_issued(world):
    document = _issue(world)
    resp = APIClient().get(f"/api/v1/public/documents/{document.public_access_token}/", HTTP_ACCEPT="text/html")
    assert resp.status_code == 200
    assert "Поставка" in resp.content.decode()


def test_public_view_404_on_draft(world):
    """A DRAFT is never served publicly — even with a token forced onto the row."""
    seller_co, seller_user = world["seller_co"], world["seller_user"]
    document, _ = crm_services.generate_document(
        seller_co, seller_user, template=_template(seller_co, seller_user), deal=world["deal"]
    )
    document.public_access_token = "forced-draft-token"
    document.save(update_fields=["public_access_token"])
    resp = APIClient().get("/api/v1/public/documents/forced-draft-token/")
    assert resp.status_code == 404


def test_public_view_404_on_cancelled(world):
    document = _issue(world)
    token = document.public_access_token
    crm_services.cancel_document(document, world["seller_user"])
    resp = APIClient().get(f"/api/v1/public/documents/{token}/")
    assert resp.status_code == 404


def test_public_view_410_on_revoked(world):
    document = _issue(world)
    document.public_token_revoked = True
    document.save(update_fields=["public_token_revoked"])
    resp = APIClient().get(f"/api/v1/public/documents/{document.public_access_token}/")
    assert resp.status_code == 410


def test_public_view_410_on_expired(world):
    document = _issue(world)
    document.public_token_expires_at = timezone.now() - timedelta(days=1)
    document.save(update_fields=["public_token_expires_at"])
    resp = APIClient().get(f"/api/v1/public/documents/{document.public_access_token}/")
    assert resp.status_code == 410


def test_public_view_404_unknown_token(world):
    resp = APIClient().get("/api/v1/public/documents/nope-nope-nope/")
    assert resp.status_code == 404


# ── II-1: send-email action ──────────────────────────────────────────────────


def test_send_email_only_issued(world):
    """A DRAFT cannot be emailed."""
    seller_co, seller_user = world["seller_co"], world["seller_user"]
    document, _ = crm_services.generate_document(
        seller_co, seller_user, template=_template(seller_co, seller_user), deal=world["deal"]
    )
    recipient, err = crm_services.send_document_email(document, seller_user, to="a@b.uz")
    assert recipient is None
    assert err == "DOCUMENT_NOT_ISSUED"


def test_send_email_action_queues(world, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    document = _issue(world)
    resp = _api(world["seller_user"]).post(
        f"/api/v1/crm/generated-documents/{document.id}/send-email/", {"to": "client@buyer.uz"}, format="json"
    )
    assert resp.status_code == 202
    assert resp.json()["to"] == "client@buyer.uz"


def test_send_email_requires_recipient(world):
    """No override, no contact/client/company email on the deal → DOCUMENT_NO_RECIPIENT."""
    document = _issue(world)
    recipient, err = crm_services.send_document_email(document, world["seller_user"])
    assert recipient is None
    assert err == "DOCUMENT_NO_RECIPIENT"


def test_send_email_buyer_cannot_send_foreign(world):
    """The buyer sees the ISSUED document (read-only) but must not be able to email it out."""
    document = _issue(world)
    recipient, err = crm_services.send_document_email(document, world["buyer_user"], to="x@y.uz")
    assert recipient is None
    assert err == "DOCUMENT_NOT_FOUND"


# ── II-2: counterparty notification on issue ─────────────────────────────────


def test_issue_notifies_counterparty(world):
    _issue(world)
    notes = Notification.objects.filter(user=world["buyer_user"])
    assert notes.count() == 1
    assert notes.first().deal_id == world["deal"].id


def test_issue_solo_deal_notifies_nobody(world):
    """A deal with no counterparty company (solo/offline) has no one to notify."""
    solo_deal = Deal.objects.create(company=None, stage=DealStage.objects.get(code="DRAFT"), title="Solo")
    _issue(world, deal=solo_deal)
    assert Notification.objects.count() == 0


# ── II-2: widened registry queryset (buyer read-only) ────────────────────────


def test_buyer_sees_received_issued_document(world):
    document = _issue(world)
    resp = _api(world["buyer_user"]).get("/api/v1/crm/generated-documents/")
    assert resp.status_code == 200
    rows = {row["id"]: row for row in resp.json()}
    assert document.id in rows
    assert rows[document.id]["is_owned"] is False  # «Получен» badge


def test_buyer_does_not_see_foreign_draft(world):
    seller_co, seller_user = world["seller_co"], world["seller_user"]
    draft, _ = crm_services.generate_document(
        seller_co, seller_user, template=_template(seller_co, seller_user), deal=world["deal"]
    )
    resp = _api(world["buyer_user"]).get("/api/v1/crm/generated-documents/")
    assert draft.id not in {row["id"] for row in resp.json()}


def test_buyer_cannot_cancel_received_document(world):
    document = _issue(world)
    resp = _api(world["buyer_user"]).post(f"/api/v1/crm/generated-documents/{document.id}/cancel/")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_NOT_FOUND"
    document.refresh_from_db()
    assert document.status_code == "ISSUED"


def test_owner_document_is_owned_true(world):
    document = _issue(world)
    resp = _api(world["seller_user"]).get("/api/v1/crm/generated-documents/")
    rows = {row["id"]: row for row in resp.json()}
    assert rows[document.id]["is_owned"] is True
    assert rows[document.id]["public_url"]


def test_buyer_of_another_company_does_not_see(world):
    document = _issue(world)
    resp = _api(world["other_user"]).get("/api/v1/crm/generated-documents/")
    assert document.id not in {row["id"] for row in resp.json()}


# ── II-4: ?deal= filter ──────────────────────────────────────────────────────


def test_deal_filter(world):
    document = _issue(world)
    other_deal = Deal.objects.create(
        company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT"), title="Другая"
    )
    _issue(world, deal=other_deal)

    resp = _api(world["seller_user"]).get(f"/api/v1/crm/generated-documents/?deal={world['deal'].id}")
    ids = {row["id"] for row in resp.json()}
    assert document.id in ids
    assert all(row["deal"] == world["deal"].id for row in resp.json())


# ── F2-3 security regressions ────────────────────────────────────────────────


def test_outsider_cannot_see_document_nor_its_link(world):
    """MAJOR-1: a user who is neither own-company staff nor the deal's buyer must NOT see the ISSUED
    document — nor obtain its secret public link."""
    outsider = CustomUser.objects.create_user(email="outsider@doc.test", username="outsider@doc.test", password="x")

    document = _issue(world)  # issued by the own company
    rows = _api(outsider).get("/api/v1/crm/generated-documents/").json()
    ids = {row["id"] for row in rows}
    assert document.id not in ids
    assert all(row.get("public_url") != document.public_url or document.public_url is None for row in rows)


def test_staff_colleague_sees_the_issued_document(world):
    """Single seller: a teammate of the issuer (own-company staff) sees the company's document."""
    colleague = _member(world["seller_co"], "colleague@doc.test", can_sell=True)
    document = _issue(world)
    ids = {row["id"] for row in _api(colleague).get("/api/v1/crm/generated-documents/").json()}
    assert document.id in ids


def test_buyer_on_deal_sees_sellers_issued_document(world):
    """Sanity companion to MAJOR-1: the BUYER (deal owner) DOES see the own company's ISSUED letter."""
    document = _issue(world)
    ids = {row["id"] for row in _api(world["buyer_user"]).get("/api/v1/crm/generated-documents/").json()}
    assert document.id in ids


def test_send_email_rejects_invalid_to(world):
    """MAJOR-2: an unvalidated `to` would turn the platform into a spam relay — reject non-emails."""
    document = _issue(world)
    resp = _api(world["seller_user"]).post(
        f"/api/v1/crm/generated-documents/{document.id}/send-email/", {"to": "not-an-email"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_EMAIL"
