"""Wave J — letterhead immutability snapshot (J-a) + revoke-public-link (J-b) for GeneratedDocument.

J-a: an ISSUED document freezes its brand шапка (лого/реквизиты/accent) into `brand_snapshot`, so it
never «плывёт» when the company later edits its profile; the PDF render reads the snapshot.
J-b: the owner can pull the public no-login link (idempotent); a non-owner / platform-admin viewer
cannot; after revoke the public view returns 410 and `public_url` null-s.

Self-contained lookup seeding (CI runs --nomigrations); fixtures mirror test_document_delivery.py.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm import services as crm_services
from crm.models import Deal, DealStage, DocumentTemplateKind, GeneratedDocumentStatus
from crm.services.generated_documents import _brand_context_from_snapshot
from notifications.models import NotificationType


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
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
    )
    if can_sell:
        _grant_head(user, company)
    return user


def _grant_head(user, company):
    """M1-ERP-05: права сотрудника — только из ролей; прежний OWNER = роль «Руководитель»."""
    from accounts.services.roles import ensure_default_company_roles

    CompanyMember.objects.get(user=user, company=company).company_roles.add(
        ensure_default_company_roles(company)["HEAD"]
    )


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _template(company, user, body="<p>{{deal.title}}</p>"):
    return crm_services.create_template(company, user, name="Письмо", kind_code="LETTER", body_html=body)


@pytest.fixture
def world(lookups):
    seller_co = _company("Seller Co", "S1", "SUPPLIER")
    seller_user = _member(seller_co, "seller@doc.test", can_sell=True)

    buyer_co = _company("Buyer Co", "B1", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@doc.test")

    deal = Deal.objects.create(company=buyer_co, stage=DealStage.objects.get(code="DRAFT"), title="Поставка")

    return {
        "seller_co": seller_co,
        "seller_user": seller_user,
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
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


# ── J-a: letterhead snapshot (immutability) ──────────────────────────────────


def test_issue_saves_nonempty_brand_snapshot(world):
    document = _issue(world)
    document.refresh_from_db()
    assert document.brand_snapshot  # non-empty
    # The issuing company's live values are frozen into the seller block.
    assert document.brand_snapshot["seller"]["name"] == "Seller Co"
    # Scalar branding keys the base template reads are present.
    for key in ("accent", "accent_contrast", "show_logo"):
        assert key in document.brand_snapshot


def test_brand_snapshot_frozen_after_company_change(world):
    document = _issue(world)
    frozen_name = document.brand_snapshot["seller"]["name"]

    seller_co = world["seller_co"]
    seller_co.name = "Renamed After Issue"
    seller_co.save(update_fields=["name"])

    document.refresh_from_db()
    # The snapshot did NOT drift with the company edit.
    assert document.brand_snapshot["seller"]["name"] == frozen_name == "Seller Co"


def test_render_context_reads_snapshot_not_live(world):
    """The PDF render path rebuilds its brand context from the frozen snapshot — a later company
    rename must not leak into it (косвенная проверка _render_generated_pdf)."""
    document = _issue(world)
    world["seller_co"].name = "Renamed After Issue"
    world["seller_co"].save(update_fields=["name"])
    document.refresh_from_db()

    brand = _brand_context_from_snapshot(document.brand_snapshot)
    assert brand["seller"].name == "Seller Co"  # frozen, not the live "Renamed After Issue"
    assert brand["seller_profile"] is None  # no profile → None stub (serializable)


def test_snapshot_freezes_document_theme_and_bank_toggle(world):
    """Preview↔PDF fidelity: the D2 theme (layout/font/tint) and the letterhead bank toggle
    _document_base.html reads must be frozen into the snapshot — else an ISSUED document's PDF
    rebuilds to the DEFAULT theme and loses the styling its DRAFT preview showed."""
    from accounts.models import CompanyDocumentProfile

    seller_co = world["seller_co"]
    # A branded, non-default theme (legal_name filled → _profile_has_branding True → profile captured).
    CompanyDocumentProfile.objects.update_or_create(
        company=seller_co,
        defaults={
            "use_company_defaults": False,
            "legal_name": "ООО «Продавец»",
            "layout_preset": "boxed",
            "font_family": "serif",
            "secondary_color": "#eef2f7",
            "bank_details": "р/с 1234, МФО 00014",
            "show_bank_in_header": True,
        },
    )

    document = _issue(world)
    document.refresh_from_db()
    snap = document.brand_snapshot

    # Theme scalars are frozen at their resolved (allowlisted) values, not dropped.
    assert snap["layout_preset"] == "boxed"
    assert "serif" in snap["font_stack"]  # _FONT_STACKS["serif"] resolved, not the raw "serif"
    assert snap["secondary"] == "#eef2f7"
    # The letterhead bank toggle survives on the frozen profile block.
    assert snap["seller_profile"]["show_bank_in_header"] is True

    # And the rebuilt render context reproduces them (what _render_generated_pdf feeds WeasyPrint).
    brand = _brand_context_from_snapshot(snap)
    assert brand["layout_preset"] == "boxed"
    assert "serif" in brand["font_stack"]
    assert brand["secondary"] == "#eef2f7"
    assert brand["seller_profile"].show_bank_in_header is True


# ── J-b: revoke public link ──────────────────────────────────────────────────


def test_owner_revokes_public_link(world):
    document = _issue(world)
    assert document.public_token_revoked is False

    revoked, err = crm_services.revoke_document_public_link(document, world["seller_user"])
    assert err is None
    revoked.refresh_from_db()
    assert revoked.public_token_revoked is True


def test_revoke_is_idempotent(world):
    document = _issue(world)
    crm_services.revoke_document_public_link(document, world["seller_user"])
    again, err = crm_services.revoke_document_public_link(document, world["seller_user"])
    assert err is None
    again.refresh_from_db()
    assert again.public_token_revoked is True


def test_non_owner_cannot_revoke(world):
    document = _issue(world)
    _, err = crm_services.revoke_document_public_link(document, world["buyer_user"])
    assert err == "DOCUMENT_NOT_FOUND"
    document.refresh_from_db()
    assert document.public_token_revoked is False


def test_revoke_draft_has_no_active_link(world):
    seller_co, seller_user = world["seller_co"], world["seller_user"]
    draft, _ = crm_services.generate_document(
        seller_co, seller_user, template=_template(seller_co, seller_user), deal=world["deal"]
    )
    _, err = crm_services.revoke_document_public_link(draft, seller_user)
    assert err == "DOCUMENT_LINK_NOT_ACTIVE"


def test_revoke_action_endpoint(world):
    document = _issue(world)
    resp = _api(world["seller_user"]).post(f"/api/v1/crm/generated-documents/{document.id}/revoke-public-link/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["public_link_revoked"] is True
    assert body["public_url"] is None  # dead link hidden from the SPA


def test_public_view_410_after_revoke(world):
    document = _issue(world)
    token = document.public_access_token
    crm_services.revoke_document_public_link(document, world["seller_user"])
    resp = APIClient().get(f"/api/v1/public/documents/{token}/")
    assert resp.status_code == 410


def test_public_url_null_after_revoke(world):
    document = _issue(world)
    crm_services.revoke_document_public_link(document, world["seller_user"])
    document.refresh_from_db()
    assert crm_services.public_document_url(document) is None
