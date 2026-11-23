"""ДВ-5: оферта и политика Кабинета — без акцепта действующей редакции кабинет не открывается.

Факт за статусом — запись `LegalAcceptance` (контакт, редакция, язык, адрес) и ответ 403 `LEGAL_ACCEPTANCE_REQUIRED` на любой
эндпоинт кабинета, кроме профиля и самих документов. Пока ничего не опубликовано, кабинет открыт как раньше (черновики из
миграции его не закрывают).
"""

import pytest
from django.conf import settings as dj_settings
from parties.models import Company, Contact
from portal import urls as portal_urls
from portal.authentication import PortalAuthentication
from portal.models import LegalAcceptance, LegalEdition
from portal.permissions import IsPortalAuthenticated
from portal.services import legal
from portal.tests.conftest import PortalAPIClient, make_portal_session
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.testing import make_own_company
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

BASE = "/api/portal/v1"
GATED = f"{BASE}/requests"
DESK = "/api/v1/settings/legal-editions/"
ACCEPTANCES = "/api/v1/settings/legal-acceptances/"


def _client(session) -> PortalAPIClient:
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


def publish_all(actor=None):
    """Опубликовать черновики из миграции обоих видов."""
    return [
        legal.release_edition(draft.pk, actor=actor) for draft in LegalEdition.objects.filter(published_at__isnull=True)
    ]


def new_edition(kind, actor=None):
    draft = legal.create_draft(kind, actor=actor)
    return legal.release_edition(draft.pk, actor=actor)


def staff(email, permissions):
    own = Company.objects.filter(name="DV5 Own Co").first() or make_own_company(
        Company.objects.create(name="DV5 Own Co", inn="505050505", legal_address="Tashkent, Test 1", phone="+998000")
    )
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    role = CompanyRole.objects.create(company=own, name=email, permissions=permissions)
    CompanyMember.objects.create(
        user=user,
        company=own,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        company_roles=[role],
        is_active=True,
        is_primary=True,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── кабинет без публикации открыт как раньше ──────────────────────────────────────────────────────────────────


def test_migration_seeds_drafts_only_and_cabinet_stays_open(portal_client):
    drafts = LegalEdition.objects.all()
    assert {d.kind for d in drafts} == {"privacy", "terms"}
    assert all(d.status == "draft" and d.label == "2026-11-23" for d in drafts)
    assert portal_client.get(GATED).status_code == 200
    me = portal_client.get(f"{BASE}/me").json()
    assert me["legal_pending"] is False
    assert portal_client.get(f"{BASE}/legal").json() == {"needs_acceptance": False, "editions": []}
    assert portal_client.get(f"{BASE}/legal/policy").json() == {"policy": None}


# ── вход закрыт, пока нет акцепта действующей редакции ───────────────────────────────────────────────────────


def test_published_edition_closes_cabinet_until_accepted(portal_client, client_contact):
    privacy, terms = publish_all()

    refused = portal_client.get(GATED)
    assert refused.status_code == 403
    assert refused.json() == {"detail": "LEGAL_ACCEPTANCE_REQUIRED"}
    assert portal_client.get(f"{BASE}/notifications").json() == {"detail": "LEGAL_ACCEPTANCE_REQUIRED"}
    assert portal_client.post(f"{BASE}/requests", {"summary": "x"}, format="json").status_code == 403
    assert not LegalAcceptance.objects.exists()

    me = portal_client.get(f"{BASE}/me")
    assert me.status_code == 200
    assert me.json()["legal_pending"] is True

    current = portal_client.get(f"{BASE}/legal").json()
    assert current["needs_acceptance"] is True
    assert {e["kind"] for e in current["editions"]} == {"privacy", "terms"}
    assert all(e["accepted"] is False for e in current["editions"])

    accepted = portal_client.post(
        f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "uz"}, format="json"
    )
    assert accepted.status_code == 200
    assert accepted.json()["needs_acceptance"] is False

    stored = LegalAcceptance.objects.filter(contact=client_contact)
    assert {(row.edition_id, row.language, row.company_id) for row in stored} == {
        (privacy.pk, "uz", client_contact.company_id),
        (terms.pk, "uz", client_contact.company_id),
    }
    assert all(row.accepted_at for row in stored)
    assert portal_client.get(GATED).status_code == 200
    assert portal_client.get(f"{BASE}/me").json()["legal_pending"] is False
    assert ActivityLog.objects.filter(event_code="portal.legal.accepted", contact_id=client_contact.pk).count() == 2


def test_accept_is_idempotent_and_records_origin(portal_client, client_contact):
    privacy, terms = publish_all()
    body = {"edition_ids": [privacy.pk, terms.pk], "language": "ru"}
    headers = {"HTTP_USER_AGENT": "Cabinet-Test/1.0", "REMOTE_ADDR": "203.0.113.7"}
    assert portal_client.post(f"{BASE}/legal/accept", body, format="json", **headers).status_code == 200
    assert portal_client.post(f"{BASE}/legal/accept", body, format="json", **headers).status_code == 200
    assert LegalAcceptance.objects.filter(contact=client_contact).count() == 2
    row = LegalAcceptance.objects.get(contact=client_contact, edition=privacy)
    assert row.user_agent == "Cabinet-Test/1.0"
    assert row.auth_method == "telegram"


def test_partial_or_stale_ids_do_not_open_cabinet(portal_client):
    privacy, terms = publish_all()
    only_one = portal_client.post(
        f"{BASE}/legal/accept", {"edition_ids": [privacy.pk], "language": "ru"}, format="json"
    )
    assert only_one.status_code == 409
    assert only_one.json() == {"detail": "LEGAL_EDITION_CHANGED"}
    assert (
        portal_client.post(
            f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "de"}, format="json"
        ).status_code
        == 422
    )
    assert not LegalAcceptance.objects.exists()
    assert portal_client.get(GATED).status_code == 403


def test_new_edition_asks_again_only_for_changed_kind_and_keeps_old_record(portal_client, client_contact):
    privacy, terms = publish_all()
    portal_client.post(f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "ru"}, format="json")
    assert portal_client.get(GATED).status_code == 200

    newer = new_edition("terms")
    assert portal_client.get(GATED).status_code == 403
    current = portal_client.get(f"{BASE}/legal").json()
    assert {(e["kind"], e["accepted"]) for e in current["editions"]} == {("privacy", True), ("terms", False)}

    # Экран, открытый до публикации, несёт старые id: принять «старое» нельзя
    stale = portal_client.post(
        f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "ru"}, format="json"
    )
    assert stale.status_code == 409
    assert portal_client.get(GATED).status_code == 403

    ok = portal_client.post(
        f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, newer.pk], "language": "en"}, format="json"
    )
    assert ok.status_code == 200
    assert portal_client.get(GATED).status_code == 200
    # Прежний акцепт старой редакции остался доказательством
    assert LegalAcceptance.objects.filter(contact=client_contact, edition=terms, language="ru").exists()
    terms.refresh_from_db()
    assert terms.status == "retired" and newer.status == "current"


def test_acceptance_is_per_contact(portal_client, client_company, client_contact):
    privacy, terms = publish_all()
    portal_client.post(f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "ru"}, format="json")
    colleague = Contact.objects.create(
        company=client_company, name="Colleague", email="colleague@example.uz", can_act=True, language="ru"
    )
    other = _client(make_portal_session(colleague, client_company, "magic_link"))
    assert portal_client.get(GATED).status_code == 200
    assert other.get(GATED).status_code == 403
    assert other.get(f"{BASE}/me").json()["legal_pending"] is True


def test_a_read_only_contact_can_accept(readonly_portal_client, readonly_contact):
    """Принять текст может любой контакт: право «действовать» для акцепта не нужно, иначе читатель остался бы за дверью."""
    privacy, terms = publish_all()
    assert readonly_portal_client.get(GATED).status_code == 403
    response = readonly_portal_client.post(
        f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "ru"}, format="json"
    )
    assert response.status_code == 200
    assert LegalAcceptance.objects.filter(contact=readonly_contact).count() == 2
    assert readonly_portal_client.get(GATED).status_code == 200


def test_only_one_kind_published_gates_on_that_kind(portal_client):
    privacy = legal.release_edition(LegalEdition.objects.get(kind="privacy").pk, actor=None)
    assert portal_client.get(GATED).status_code == 403
    portal_client.post(f"{BASE}/legal/accept", {"edition_ids": [privacy.pk], "language": "ru"}, format="json")
    assert portal_client.get(GATED).status_code == 200


def test_all_cabinet_entry_points_are_gated_by_construction():
    """Любая вьюха портала с сессией проходит `IsPortalAuthenticated` (там гейт); без акцепта открыты только три вьюхи."""
    exempt, unguarded = set(), []
    for pattern in portal_urls.urlpatterns:
        view = pattern.callback.view_class
        if PortalAuthentication not in getattr(view, "authentication_classes", ()):
            continue
        if not any(issubclass(p, IsPortalAuthenticated) for p in view.permission_classes):
            unguarded.append(view.__name__)
        if getattr(view, "legal_exempt", False):
            exempt.add(view.__name__)
    # Выход открыт всегда: отказ от оферты — это выход, он должен работать без акцепта
    unguarded = {name for name in unguarded if name != "LogoutView"}
    assert not unguarded, f"вьюхи с сессией без IsPortalAuthenticated обходят гейт акцепта: {unguarded}"
    assert exempt == {"MeView", "LegalCurrentView", "LegalAcceptView"}


def test_logout_works_without_acceptance(portal_client):
    """Отказ принять — выход: он не должен упираться в тот же гейт."""
    publish_all()
    assert portal_client.get(GATED).status_code == 403
    assert portal_client.post(f"{BASE}/auth/logout", {}, format="json").status_code in (200, 204)
    assert portal_client.get(f"{BASE}/me").status_code == 401


def test_telegram_miniapp_session_is_gated_too(settings, client_contact, client_company, bot_token):
    """Вход из Telegram даёт ту же сессию — и тот же гейт; `Me` сразу несёт признак."""
    from portal.tests.conftest import make_telegram_init_data

    publish_all()
    api = PortalAPIClient()
    response = api.post(
        f"{BASE}/auth/telegram",
        {"init_data": make_telegram_init_data(client_contact.telegram_user_id)},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["legal_pending"] is True
    assert api.get(GATED).status_code == 403


# ── публичная политика и подстановки ──────────────────────────────────────────────────────────────────────────


def test_public_policy_is_readable_without_session_with_company_requisites(client):
    staff("owner@own.example", ["settings.edit"])
    assert client.get(f"{BASE}/legal/policy").json() == {"policy": None}
    privacy, terms = publish_all()
    body = client.get(f"{BASE}/legal/policy").json()["policy"]
    assert body["id"] == privacy.pk and body["kind"] == "privacy"
    assert set(body["title"]) == {"ru", "uz", "en"}
    flat = " ".join(section["body"]["ru"] for section in body["sections"]) + body["lead"]["ru"]
    assert "{{" not in flat
    assert "DV5 Own Co" in flat and "505050505" in flat


def test_render_fills_placeholders_and_marks_missing_values():
    values = {"name": "ACME", "inn": "", "address": "Addr", "support_email": "s@a.uz", "phone": "+1"}
    text = {
        "title": {"ru": "{{company.name}}"},
        "lead": {},
        "sections": [{"title": {}, "body": {"en": "INN {{company.inn}}; {{ company.phone }}"}}],
    }
    out = legal.render_content(text, values)
    assert out["title"]["ru"] == "ACME"
    assert out["sections"][0]["body"]["en"] == "INN —; +1"


# ── «Настройки»: редакции, публикация, журнал ─────────────────────────────────────────────────────────────────


def test_desk_requires_settings_edit():
    nobody = staff("nobody@own.example", ["catalog.manage"])
    assert nobody.get(DESK).status_code == 403
    assert nobody.get(ACCEPTANCES).status_code == 403
    assert nobody.post(DESK, {"kind": "terms"}, format="json").status_code == 403
    LegalEdition.objects.filter(kind="terms")  # черновик не тронут
    assert LegalEdition.objects.filter(kind="terms", published_at__isnull=True).exists()


def test_desk_lists_edits_and_publishes_with_audit():
    director = staff("director@own.example", ["settings.edit"])
    listing = director.get(DESK).json()["results"]
    assert {(row["kind"], row["status"]) for row in listing} == {("privacy", "draft"), ("terms", "draft")}

    draft = next(row for row in listing if row["kind"] == "terms")
    detail = director.get(f"{DESK}{draft['id']}/").json()
    assert len(detail["content"]["sections"]) == 17
    assert "{{company.name}}" in detail["content"]["lead"]["ru"] and "{{" not in detail["rendered"]["lead"]["ru"]

    content = detail["content"]
    content["sections"][0]["body"]["ru"] += "\nДополнение."
    patched = director.patch(f"{DESK}{draft['id']}/", {"label": "2026-12-01", "content": content}, format="json")
    assert patched.status_code == 200 and patched.json()["label"] == "2026-12-01"
    assert patched.json()["content"]["sections"][0]["body"]["ru"].endswith("Дополнение.")

    bad = director.patch(f"{DESK}{draft['id']}/", {"content": {"title": {}, "sections": []}}, format="json")
    assert bad.status_code == 400

    published = director.post(f"{DESK}{draft['id']}/publish/")
    assert published.status_code == 200 and published.json()["status"] == "current"
    assert published.json()["published_by"]
    entry = ActivityLog.objects.get(event_code="admin.portal_legal.published")
    assert entry.event_params["edition"] == "2026-12-01" and entry.user is not None

    # опубликованное не правится и не публикуется повторно, черновик нового издания — копия действующей
    assert director.patch(f"{DESK}{draft['id']}/", {"label": "x"}, format="json").status_code == 409
    assert director.post(f"{DESK}{draft['id']}/publish/").status_code == 409
    created = director.post(DESK, {"kind": "terms"}, format="json")
    assert created.status_code == 201 and created.json()["status"] == "draft"
    assert created.json()["content"] == content
    assert director.post(DESK, {"kind": "terms"}, format="json").json() == {"detail": "LEGAL_DRAFT_EXISTS"}
    assert director.delete(f"{DESK}{created.json()['id']}/").status_code == 204


def test_publish_retires_previous_and_keeps_one_current(portal_client):
    director = staff("director2@own.example", ["settings.edit"])
    privacy, terms = publish_all(actor=None)
    created = director.post(DESK, {"kind": "privacy"}, format="json").json()
    director.post(f"{DESK}{created['id']}/publish/")
    current = LegalEdition.objects.filter(kind="privacy", published_at__isnull=False, retired_at__isnull=True)
    assert [e.pk for e in current] == [created["id"]]
    privacy.refresh_from_db()
    assert privacy.status == "retired"


def test_acceptance_log_lists_who_when_which_edition(portal_client, client_contact):
    director = staff("director3@own.example", ["settings.edit"])
    privacy, terms = publish_all()
    portal_client.post(f"{BASE}/legal/accept", {"edition_ids": [privacy.pk, terms.pk], "language": "uz"}, format="json")
    page = director.get(ACCEPTANCES).json()
    assert page["count"] == 2
    row = next(item for item in page["results"] if item["kind"] == "privacy")
    assert row["edition"] == "2026-11-23" and row["language"] == "uz"
    assert row["contact"]["email"] == client_contact.email and row["company"]["id"] == client_contact.company_id
    assert director.get(f"{ACCEPTANCES}?edition={terms.pk}").json()["count"] == 1
    assert director.get(f"{ACCEPTANCES}?q=nonexistent").json()["count"] == 0
    counts = {r["id"]: r["acceptances_count"] for r in director.get(DESK).json()["results"]}
    assert counts[privacy.pk] == 1 and counts[terms.pk] == 1
