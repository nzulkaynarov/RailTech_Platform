"""D1–D2 document theme: brand edits invalidate mutable cached PDFs; the theme fields
(layout preset / font / secondary tint) validate + persist; the multi-type Document-Layout
preview renders every kind with draft (unsaved) overrides — Odoo wizard model.
"""

from datetime import date

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.services.document_profile import update_document_profile
from crm.services.documents import PREVIEW_DOC_TYPES, render_document_profile_preview_html


def _owner(company, email):
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_primary=True, is_active=True)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def seller(db):
    company = Company.objects.create(name="РемПуть-Тема", inn="6300000001")
    owner = _owner(company, "theme-owner@a.test")
    return company, owner


# ── Theme fields: validation + persistence ────────────────────────────────────────


@pytest.mark.django_db
def test_theme_fields_persist(seller):
    company, owner = seller
    profile, error = update_document_profile(
        owner,
        company,
        {"layout_preset": "striped", "font_family": "serif", "secondary_color": "#eef2f7"},
    )
    assert error is None
    profile.refresh_from_db()
    assert profile.layout_preset == "striped"
    assert profile.font_family == "serif"
    assert profile.secondary_color == "#eef2f7"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload,code",
    [
        ({"layout_preset": "neon"}, "INVALID_LAYOUT_PRESET"),
        ({"font_family": "comic-sans"}, "INVALID_FONT_FAMILY"),
        ({"secondary_color": "red;background:url(http://10.0.0.2)"}, "INVALID_SECONDARY_COLOR"),
    ],
)
def test_theme_fields_validated(seller, payload, code):
    company, owner = seller
    profile, error = update_document_profile(owner, company, payload)
    assert profile is None
    assert error == code


# ── D1a: brand edits invalidate still-mutable cached PDFs ─────────────────────────


@pytest.fixture
def quotes_with_pdfs(seller):
    from crm.models import Deal, DealStage, Quote

    company, owner = seller
    buyer = Company.objects.create(name="Покупатель-Тема", inn="6300000002")
    stage = DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 1})[0]
    deal = Deal.objects.create(title="Тема-сделка", company=buyer, stage=stage)
    draft = Quote.objects.create(deal=deal, seller_company=company, version=1, pdf_file="quotes/draft.pdf")
    frozen = Quote.objects.create(
        deal=deal, seller_company=company, version=2, pdf_file="quotes/frozen.pdf", frozen_at=timezone.now()
    )
    return company, owner, draft, frozen


@pytest.mark.django_db
def test_brand_edit_invalidates_draft_quote_pdf_keeps_frozen(quotes_with_pdfs):
    company, owner, draft, frozen = quotes_with_pdfs
    _, error = update_document_profile(owner, company, {"accent_color": "#8b0000"})
    assert error is None
    draft.refresh_from_db()
    frozen.refresh_from_db()
    # The unfrozen КП's cached PDF is stale brand → cleared (lazy re-render on next download);
    # the frozen КП is the client-received snapshot and NEVER changes (PandaDoc model).
    assert not draft.pdf_file
    assert frozen.pdf_file.name == "quotes/frozen.pdf"


@pytest.mark.django_db
def test_noop_update_does_not_invalidate(quotes_with_pdfs):
    company, owner, draft, _frozen = quotes_with_pdfs
    _, error = update_document_profile(owner, company, {})  # nothing changed
    assert error is None
    draft.refresh_from_db()
    assert draft.pdf_file.name == "quotes/draft.pdf"


# ── D1b: multi-type preview + draft overrides (WYSIWYG) ───────────────────────────


@pytest.mark.django_db
def test_preview_renders_every_type_with_draft_theme(seller):
    company, _owner_user = seller
    for doc_type in PREVIEW_DOC_TYPES:
        html = render_document_profile_preview_html(
            company,
            doc_type=doc_type,
            overrides={
                "layout_preset": "boxed",
                "font_family": "serif",
                "accent_color": "#8b0000",
                "secondary_color": "#fdf0f0",
            },
        )
        assert "layout-boxed" in html, doc_type
        assert "#8b0000" in html, doc_type
        assert "DejaVu Serif" in html, doc_type
        assert "#fdf0f0" in html, doc_type


@pytest.mark.django_db
def test_preview_defaults_reproduce_light_layout(seller):
    company, _owner_user = seller
    html = render_document_profile_preview_html(company)
    assert "layout-light" in html
    assert "DejaVu Sans" in html


@pytest.mark.django_db
def test_preview_endpoint_post_draft(seller):
    company, owner = seller
    resp = _client(owner).post(
        f"/api/v1/accounts/companies/{company.id}/document-profile/preview/",
        {"doc_type": "CT", "draft": {"layout_preset": "bold", "accent_color": "#005500"}},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "layout-bold" in body
    assert "#005500" in body


@pytest.mark.django_db
def test_preview_endpoint_rejects_unknown_type(seller):
    company, owner = seller
    resp = _client(owner).post(
        f"/api/v1/accounts/companies/{company.id}/document-profile/preview/",
        {"doc_type": "EVIL"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_PREVIEW_DOC_TYPE"


@pytest.mark.django_db
def test_preview_draft_never_persists(seller):
    from accounts.models import CompanyDocumentProfile

    company, _owner_user = seller
    render_document_profile_preview_html(company, doc_type="KP", overrides={"layout_preset": "striped"})
    row = CompanyDocumentProfile.objects.filter(company=company).first()
    # The preview never creates/saves a profile row — overrides are in-memory only.
    assert row is None or row.layout_preset == "light"
