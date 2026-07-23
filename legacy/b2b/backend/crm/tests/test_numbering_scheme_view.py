"""N2 — document-numbering-scheme editor endpoints (Settings → «Нумерация»).

Covers the thin DRF surface over the N1 service:
  * GET returns the effective scheme + prefix + is_effective (prefixed vs prefix-less);
  * PATCH upserts a valid scheme and echoes it back;
  * PATCH with an invalid mask (no {seq}) → 400 {"detail": "INVALID_NUMBERING_PATTERN"};
  * POST preview renders КП/CT/INV examples WITHOUT incrementing any counter;
  * gate: a non-seller (no seller company) is refused 403;
  * preview echoes the draft mask (single source of truth = the real token parser).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanySettings, CompanyType, CustomUser, WorkspaceRole
from crm.models import DocumentNumberingScheme, DocumentSequence

pytestmark = pytest.mark.django_db


def _seller_company(name, inn, prefix=""):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    if prefix:
        CompanySettings.objects.create(company=company, doc_number_prefix=prefix)
    return company


def _owner(company, email):
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_primary=True, is_active=True, can_sell=True)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


URL = "/api/v1/crm/numbering-scheme/"
PREVIEW_URL = "/api/v1/crm/numbering-scheme/preview/"


# ── GET ─────────────────────────────────────────────────────────────────────────────


def test_get_effective_scheme_prefixed():
    company = _seller_company("ACME", "6200000001", prefix="ACME")
    resp = _client(_owner(company, "owner@acme.test")).get(URL)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["pattern"] == DocumentNumberingScheme.DEFAULT_PATTERN
    assert body["padding"] == DocumentNumberingScheme.DEFAULT_PADDING
    assert body["prefix"] == "ACME"
    assert body["is_effective"] is True


def test_get_prefixless_is_not_effective():
    company = _seller_company("Plain", "6200000002")
    resp = _client(_owner(company, "owner@plain.test")).get(URL)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["prefix"] == ""
    assert body["is_effective"] is False


# ── PATCH ───────────────────────────────────────────────────────────────────────────


def test_patch_upserts_and_echoes_scheme():
    company = _seller_company("ACME", "6200000003", prefix="ACME")
    resp = _client(_owner(company, "owner@acme3.test")).patch(
        URL,
        {"pattern": "{type}/{YYYY}/{seq}", "padding": 6, "reset_period": "monthly", "start_value": 100},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["pattern"] == "{type}/{YYYY}/{seq}"
    assert body["padding"] == 6
    assert body["reset_period"] == "monthly"
    assert body["start_value"] == 100
    row = DocumentNumberingScheme.objects.get(company=company)
    assert row.pattern == "{type}/{YYYY}/{seq}"
    assert row.padding == 6


def test_patch_invalid_pattern_returns_code():
    company = _seller_company("ACME", "6200000004", prefix="ACME")
    resp = _client(_owner(company, "owner@acme4.test")).patch(
        URL, {"pattern": "{prefix}{type}-{YYYY}"}, format="json"  # no {seq}
    )
    assert resp.status_code == 400, resp.content
    assert resp.json() == {"detail": "INVALID_NUMBERING_PATTERN"}
    assert not DocumentNumberingScheme.objects.filter(company=company).exists()


# ── Preview (dry-run) ─────────────────────────────────────────────────────────────────


def test_preview_renders_all_editable_types_without_counter():
    company = _seller_company("ACME", "6200000005", prefix="ACME")
    resp = _client(_owner(company, "owner@acme5.test")).post(
        PREVIEW_URL,
        {"pattern": "{prefix}{type}-{YYYY}-{seq}", "padding": 5, "reset_period": "yearly", "start_value": 0},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    results = resp.json()["results"]
    codes = {r["type_code"]: r["number"] for r in results}
    assert set(codes) == {"KP", "CT", "INV", "ACT", "DOC"}
    from django.utils import timezone

    year = timezone.now().year
    assert codes["KP"] == f"ACME-КП-{year}-00001"
    assert codes["CT"] == f"ACME-CT-{year}-00001"
    assert codes["INV"] == f"ACME-INV-{year}-00001"
    # Dry-run: no counter row was created / touched.
    assert not DocumentSequence.objects.filter(company=company).exists()


def test_preview_reflects_draft_prefix_and_type_labels():
    """The editor's UNSAVED prefix + type-label edits render live in the dry-run (WYSIWYG)."""
    company = _seller_company("BETA", "6200000055", prefix="")  # no persisted prefix yet
    resp = _client(_owner(company, "owner@beta55.test")).post(
        PREVIEW_URL,
        {
            "pattern": "{prefix}{type}-{YYYY}-{seq}",
            "padding": 5,
            "reset_period": "yearly",
            "start_value": 0,
            "prefix": "BETA",
            "type_labels": {"CT": "ДОГ", "INV": "СЧ"},
        },
        format="json",
    )
    assert resp.status_code == 200, resp.content
    codes = {r["type_code"]: r["number"] for r in resp.json()["results"]}
    from django.utils import timezone

    year = timezone.now().year
    assert codes["CT"] == f"BETA-ДОГ-{year}-00001"  # draft prefix + draft label both applied
    assert codes["INV"] == f"BETA-СЧ-{year}-00001"
    assert codes["KP"] == f"BETA-КП-{year}-00001"  # unset label falls back to shipped default


def test_preview_reflects_draft_start_value():
    company = _seller_company("ACME", "6200000006", prefix="ACME")
    resp = _client(_owner(company, "owner@acme6.test")).post(
        PREVIEW_URL,
        {"pattern": "{type}-{seq}", "padding": 4, "reset_period": "never", "start_value": 1000},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    codes = {r["type_code"]: r["number"] for r in resp.json()["results"]}
    # first number = start_value + 1
    assert codes["CT"] == "CT-1001"


def test_preview_invalid_pattern_returns_code():
    company = _seller_company("ACME", "6200000007", prefix="ACME")
    resp = _client(_owner(company, "owner@acme7.test")).post(
        PREVIEW_URL,
        {"pattern": "{type}-{YYYY}", "padding": 5, "reset_period": "yearly", "start_value": 0},
        format="json",
    )
    assert resp.status_code == 400, resp.content
    assert resp.json() == {"detail": "INVALID_NUMBERING_PATTERN"}


# ── Gate ──────────────────────────────────────────────────────────────────────────────


def test_non_seller_is_refused():
    """A user whose only company is NOT a seller (no SUPPLIER type) has no seller company
    → 403 on every numbering-scheme verb."""
    company = Company.objects.create(name="BuyerCo", inn="6200000008")
    ws = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email="buyer@b.test", username="buyer@b.test", password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=ws, is_primary=True, is_active=True)
    client = _client(user)
    assert client.get(URL).status_code == 403
    assert client.patch(URL, {"pattern": "{type}-{seq}"}, format="json").status_code == 403
    assert (
        client.post(
            PREVIEW_URL,
            {"pattern": "{type}-{seq}", "padding": 5, "reset_period": "yearly", "start_value": 0},
            format="json",
        ).status_code
        == 403
    )


def test_unauthenticated_is_refused():
    assert APIClient().get(URL).status_code in (401, 403)
