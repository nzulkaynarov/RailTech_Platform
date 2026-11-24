# flake8: noqa: F811
"""«Ссылка клиента в Кабинете» у договора, счёта и акта для сотрудника (ДК-3б).

Факт, из которого выводится состояние: у каждой ссылки — `revoked_at`, срок и видимость документа; отзыв гасит ссылки
ЭТОГО документа у всех получателей и пишет событие в журнал сделки; чужие документы не затрагиваются; право — то же, что
на отправку документа; адрес получателя наружу — только замаскированный.
"""

from __future__ import annotations

import pytest
from portal.models import DocumentLink
from portal.services import doc_links

# Фикстуры документов и окружения — из соседнего набора ДК-3.
from portal.tests.test_doc_links_kinds import (  # noqa: F401 — фикстуры pytest
    _env,
    act,
    contract,
    deal,
    invoice,
    mint,
    quote,
)
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember, CustomUser, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

URL = {"contract": "contracts", "invoice": "invoices", "act": "acts"}
#: Роль, которая отправляет документ этого вида (`required_permissions` вьюхи).
SENDER_ROLE = {"contract": "HEAD", "invoice": "HEAD", "act": "HEAD"}


def _staff(seller_company, email, role_code):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    ws, _ = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    member = CompanyMember.objects.create(user=user, company=seller_company, role=ws, is_active=True, is_primary=True)
    member.company_roles.add(ensure_default_company_roles(seller_company)[role_code])
    return user


def _api(user):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return api


@pytest.fixture
def sender(seller_company):
    return _api(_staff(seller_company, "head@seller.test", "HEAD"))


@pytest.fixture
def viewer(seller_company):
    return _api(_staff(seller_company, "viewer@seller.test", "VIEWER"))


def _url(kind, doc, tail):
    return f"/api/v1/crm/{URL[kind]}/{doc.pk}/{tail}/"


KINDS = ["contract", "invoice", "act"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_list_shows_every_recipient_masked(kind, request, sender, client_contact):
    doc = request.getfixturevalue(kind)
    mint(kind, doc)
    mint(kind, doc, email="second@other.example.uz", name="Второй")
    response = sender.get(_url(kind, doc, "client-links"))
    assert response.status_code == 200
    body = response.json()
    hints = sorted(row["recipient_hint"] for row in body["links"])
    assert hints == ["a***@example.uz", "s***@other.example.uz"]
    assert "azamat.client" not in response.content.decode() and "second@" not in response.content.decode()
    assert {row["state"] for row in body["links"]} == {"active"} and body["can_revoke"] is True
    assert all(row["first_opened_at"] is None for row in body["links"])


@pytest.mark.parametrize("kind", KINDS)
def test_revoke_kills_only_this_documents_links(kind, request, sender, contract, invoice, act):
    doc = request.getfixturevalue(kind)
    mint(kind, doc)
    mint(kind, doc, email="second@other.example.uz")
    others = [(k, request.getfixturevalue(k)) for k in KINDS if k != kind]
    for other_kind, other in others:
        mint(other_kind, other)
    response = sender.post(_url(kind, doc, "revoke-client-links"))
    assert response.status_code == 200
    body = response.json()
    assert {row["state"] for row in body["links"]} == {"revoked"} and body["can_revoke"] is False
    assert not DocumentLink.objects.filter(kind=kind, revoked_at__isnull=True).exists()
    assert DocumentLink.objects.filter(revoked_at__isnull=True).count() == len(others)  # чужие живы


def test_revoke_does_not_touch_the_same_kind_of_another_document(sender, invoice, deal):
    from crm.models import Invoice

    twin = Invoice.objects.create(deal=deal, contract=invoice.contract, number="INV-2", status=invoice.status)
    mint("invoice", invoice)
    mint("invoice", twin)
    sender.post(_url("invoice", invoice, "revoke-client-links"))
    assert DocumentLink.objects.get(invoice=invoice).revoked_at is not None
    assert DocumentLink.objects.get(invoice=twin).revoked_at is None


@pytest.mark.parametrize("kind", KINDS)
def test_revoke_writes_the_journal_event_once(kind, request, sender):
    doc = request.getfixturevalue(kind)
    mint(kind, doc)
    sender.post(_url(kind, doc, "revoke-client-links"))
    sender.post(_url(kind, doc, "revoke-client-links"))  # повтор — без второй записи
    rows = ActivityLog.objects.filter(entity_type=kind, entity_id=doc.pk, event_code=f"{kind}.link_revoked")
    assert rows.count() == 1 and rows.get().user_id is not None


@pytest.mark.parametrize("kind", KINDS)
def test_a_revoked_link_answers_gone(kind, request, sender):
    from portal.tests.test_doc_links import open_

    doc = request.getfixturevalue(kind)
    _, raw = mint(kind, doc)
    assert open_(raw).status_code == 200
    sender.post(_url(kind, doc, "revoke-client-links"))
    assert open_(raw).status_code == 410


@pytest.mark.parametrize("kind", KINDS)
def test_without_the_right_to_send_the_list_and_the_revoke_are_403(kind, request, viewer):
    doc = request.getfixturevalue(kind)
    link, _ = mint(kind, doc)
    assert viewer.get(_url(kind, doc, "client-links")).status_code == 403
    assert viewer.post(_url(kind, doc, "revoke-client-links")).status_code == 403
    link.refresh_from_db()
    assert link.revoked_at is None


@pytest.mark.parametrize("kind", KINDS)
def test_anonymous_is_refused(kind, request):
    doc = request.getfixturevalue(kind)
    assert APIClient().get(_url(kind, doc, "client-links")).status_code in (401, 403)


def test_the_state_follows_the_facts_not_the_row(invoice):
    link, _ = mint("invoice", invoice)
    assert doc_links.document_link_rows("invoice", invoice)[0]["state"] == "active"
    link.expires_at = link.created_at.replace(year=2000)
    link.save()
    assert doc_links.document_link_rows("invoice", invoice)[0]["state"] == "expired"
