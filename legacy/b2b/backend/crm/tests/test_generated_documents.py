"""«Документы 2.0» — generation lifecycle: snapshot immutability, DRAFT-only edit +
PDF invalidation, issue/cancel transitions, entitlement + IDOR gates.

Self-contained lookup seeding (CI runs --nomigrations)."""

import pytest
from django.core.files.base import ContentFile

from accounts.constants import FeatureKey
from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from accounts.services.entitlements import grant_entitlement
from crm import services as crm_services
from crm.models import (
    DealStage,
    DocumentTemplate,
    DocumentTemplateKind,
    GeneratedDocumentStatus,
)


@pytest.fixture
def lookups(db):
    for code, name in (("LETTER", "Письмо"), ("CUSTOM", "Произвольный")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "CANCELLED"):
        GeneratedDocumentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})


def _company(name, inn):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


def _member(company, email):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    return user


def _deal(company, title):
    from crm.models import Deal

    return Deal.objects.create(company=company, stage=DealStage.objects.get(code="DRAFT"), title=title)


def _template(company, user, body="<p>{{deal.title}} — {{today}}</p>"):
    return crm_services.create_template(company, user, name="Письмо", kind_code="LETTER", body_html=body)


@pytest.fixture
def entitled_world(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "s@t.uz")
    grant_entitlement(company.id, FeatureKey.DOCUMENT_GENERATE)
    return company, user


# ── Generation + snapshot immutability ───────────────────────────────────────


def test_generate_creates_draft_snapshot(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "Поставка рельсов")
    document, err = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    assert err is None
    assert document.status_code == "DRAFT"
    assert "Поставка рельсов" in document.rendered_html
    assert document.values.get("deal.title") == "Поставка рельсов"
    assert document.number


def test_snapshot_does_not_drift_when_source_changes(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "Старое название")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    deal.title = "Новое название"
    deal.save(update_fields=["title"])
    document.refresh_from_db()
    assert "Старое название" in document.rendered_html
    assert "Новое название" not in document.rendered_html


# ── DRAFT-only edit + PDF invalidation ───────────────────────────────────────


def test_update_values_only_draft_and_invalidates_pdf(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    document.pdf_file.save("stale.pdf", ContentFile(b"%PDF-old"), save=True)
    assert document.pdf_file

    updated, err = crm_services.update_document_values(document, {"today": "перекрыто"})
    assert err is None
    assert not updated.pdf_file  # invalidate-on-write
    assert "перекрыто" in updated.rendered_html


def test_update_values_rejected_after_issue(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    crm_services.issue_document(document, user)
    document.refresh_from_db()
    _, err = crm_services.update_document_values(document, {"today": "x"})
    assert err == "DOCUMENT_NOT_EDITABLE"


# ── Status transitions ───────────────────────────────────────────────────────


def test_issue_transitions_draft_to_issued(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    issued, err = crm_services.issue_document(document, user)
    assert err is None
    assert issued.status_code == "ISSUED"
    assert issued.issued_at is not None


def test_double_issue_rejected(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    crm_services.issue_document(document, user)
    document.refresh_from_db()
    _, err = crm_services.issue_document(document, user)
    assert err == "DOCUMENT_ALREADY_ISSUED"


def test_cancel_then_recancel_rejected(entitled_world):
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    cancelled, err = crm_services.cancel_document(document, user)
    assert err is None
    assert cancelled.status_code == "CANCELLED"
    _, err2 = crm_services.cancel_document(document, user)
    assert err2 == "DOCUMENT_ALREADY_CANCELLED"


# ── Gates: entitlement + IDOR ────────────────────────────────────────────────


def test_generate_requires_entitlement(lookups):
    company = _company("NoSub", "N1")  # no grant_entitlement
    user = _member(company, "n@t.uz")
    deal = _deal(company, "T")
    document, err = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    assert document is None
    assert err == "SUBSCRIPTION_REQUIRED"


def test_generate_rejects_foreign_deal_idor(entitled_world):
    company, user = entitled_world
    other = _company("Other", "O1")
    other_user = _member(other, "o@t.uz")
    foreign_deal = _deal(other, "Чужая сделка")
    document, err = crm_services.generate_document(
        company, user, template=_template(company, user), deal=foreign_deal
    )
    assert document is None
    assert err == "DEAL_NOT_FOUND"


# ── A4 hardening regressions ─────────────────────────────────────────────────


def test_draft_rerender_uses_body_snapshot_not_live_template(entitled_world):
    """A4/M2: editing the template AFTER generation must not rewrite an existing draft."""
    company, user = entitled_world
    deal = _deal(company, "T")
    template = _template(company, user, body="<p>Здравствуйте, {{company.name}}!</p>")
    document, _ = crm_services.generate_document(company, user, template=template, deal=deal)
    assert document.body_html_snapshot == "<p>Здравствуйте, {{company.name}}!</p>"
    # Admin later rewrites the shared template.
    crm_services.update_template(template, body_html="<p>ВЗЛОМ {{company.name}}</p>")
    # A values edit on the draft re-renders off the FROZEN snapshot, not the new body.
    updated, err = crm_services.update_document_values(document, {})
    assert err is None
    assert "Здравствуйте" in updated.rendered_html
    assert "ВЗЛОМ" not in updated.rendered_html


def test_update_values_rejects_unknown_keys(entitled_world):
    """A4/m6: only known snapshot placeholder codes may be set."""
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    updated, err = crm_services.update_document_values(document, {"evil.injected": "x", "system.secret": "y"})
    assert err is None
    assert "evil.injected" not in updated.values
    assert "system.secret" not in updated.values


def test_issue_rechecks_entitlement(entitled_world):
    """A4/m4: a lapsed subscription can't issue a draft created while subscribed."""
    from accounts.services.entitlements import grant_entitlement

    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    grant_entitlement(company.id, FeatureKey.DOCUMENT_GENERATE, access="DISABLED")
    _, err = crm_services.issue_document(document, user)
    assert err == "SUBSCRIPTION_REQUIRED"


def test_cancel_clears_pdf(entitled_world):
    """A4/m7: a cancelled document must not keep a downloadable PDF."""
    company, user = entitled_world
    deal = _deal(company, "T")
    document, _ = crm_services.generate_document(company, user, template=_template(company, user), deal=deal)
    document.pdf_file.save("doc.pdf", ContentFile(b"%PDF-x"), save=True)
    assert document.pdf_file
    cancelled, err = crm_services.cancel_document(document, user)
    assert err is None
    assert not cancelled.pdf_file


def test_create_template_rejects_oversize_body(lookups):
    company = _company("Seller", "S1")
    user = _member(company, "s@t.uz")
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        crm_services.create_template(company, user, name="Big", kind_code="LETTER", body_html="x" * 100_001)
