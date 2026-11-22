"""D1–D2 document theme: brand edits invalidate mutable cached PDFs; the multi-type Document-Layout preview renders
every kind with draft (unsaved) overrides. ДОК-13: the layout / font / second colour settings are gone — the service
neither stores nor validates them, and no template reads them.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from accounts.services.document_profile import update_document_profile
from accounts.testing import grant_head, make_own_company
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
    company = make_own_company(Company.objects.create(name="РемПуть-Тема", inn="6300000001"))
    owner = _owner(company, "theme-owner@a.test")
    grant_head(owner, company)
    return company, owner


# ── ДОК-13: «Макет», «Шрифт», «Второй цвет» удалены ──────────────────────────────────


@pytest.mark.django_db
def test_removed_theme_fields_are_not_stored(seller):
    company, owner = seller
    profile, error = update_document_profile(
        owner,
        company,
        {"layout_preset": "striped", "font_family": "serif", "secondary_color": "#eef2f7", "accent_color": "#8b0000"},
    )
    assert error is None
    profile.refresh_from_db()
    assert profile.accent_color == "#8b0000"  # the colour that stays is saved
    assert (profile.layout_preset, profile.font_family, profile.secondary_color) == ("light", "sans", "")


@pytest.mark.django_db
def test_removed_theme_fields_are_not_validated(seller):
    """A value that used to be refused is now simply ignored — nothing reads it, nothing lands in a PDF."""
    company, owner = seller
    profile, error = update_document_profile(owner, company, {"secondary_color": "red;background:url(http://10.0.0.2)"})
    assert error is None


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
def test_preview_renders_every_type_with_draft_accent_and_ignores_removed_theme(seller):
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
        assert "#8b0000" in html, doc_type
        assert "layout-" not in html, doc_type
        assert "DejaVu Serif" not in html, doc_type
        assert "#fdf0f0" not in html, doc_type


@pytest.mark.django_db
def test_preview_defaults_use_one_look(seller):
    company, _owner_user = seller
    html = render_document_profile_preview_html(company)
    assert "layout-" not in html
    assert "DejaVu Sans" in html


@pytest.mark.django_db
def test_preview_endpoint_post_draft(seller):
    company, owner = seller
    resp = _client(owner).post(
        f"/api/v1/accounts/companies/{company.id}/document-profile/preview/",
        {"doc_type": "CT", "draft": {"accent_color": "#005500"}},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
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
    render_document_profile_preview_html(company, doc_type="KP", overrides={"accent_color": "#123456"})
    row = CompanyDocumentProfile.objects.filter(company=company).first()
    # The preview never creates/saves a profile row — overrides are in-memory only.
    assert row is None or row.accent_color == ""
