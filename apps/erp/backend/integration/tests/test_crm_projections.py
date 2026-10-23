"""Проекции ERP по событиям CRM (B3, L13): `client.updated`, `contact.created|updated|deleted` (CONTRACTS §9, ADR-0015 п. 5).

Снимки с `updated_at` (у удаления — `deleted_at`): более старый уже применённого не применяется, повтор — без действий,
неизвестный клиент — пропуск с записью, не ошибка. ERP обновляет только поля, которыми владеет CRM (имя и контакты клиента);
реквизиты (ИНН) и права контакта в Cabinet — свои.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from integration.models import CrmContactMapping, CrmProjectionState
from integration.services import crm_projections as projections
from integration.tests.world import make_company
from parties.models import Company, Contact
from portal.models import PortalSession

pytestmark = pytest.mark.django_db

EVENTS_DIR = Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events"))
T0 = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def example(name: str) -> dict:
    return json.loads((EVENTS_DIR / "crm" / "examples" / f"{name}.v1.json").read_text(encoding="utf-8"))["data"]


def client_data(crm_client_id=42, *, name="Новое имя", at=T0, inn="999000111"):
    data = example("client.updated")
    data["client"].update(
        {"crm_client_id": crm_client_id, "name": name, "inn": inn, "updated_at": at.isoformat().replace("+00:00", "Z")}
    )
    return data


def contact_data(crm_contact_id=58, crm_client_id=42, *, at=T0, **fields):
    data = example("contact.created")
    data["contact"].update(
        {
            "crm_contact_id": crm_contact_id,
            "crm_client_id": crm_client_id,
            "updated_at": at.isoformat().replace("+00:00", "Z"),
            **fields,
        }
    )
    return data


def deleted_data(crm_contact_id=58, crm_client_id=42, *, at=T0):
    data = example("contact.deleted")
    data.update(
        {
            "crm_contact_id": crm_contact_id,
            "crm_client_id": crm_client_id,
            "deleted_at": at.isoformat().replace("+00:00", "Z"),
        }
    )
    return data


@pytest.fixture
def company():
    return make_company(name="ООО Клиент", crm_client_id=42, inn="123456789")


# ── client.updated ──────────────────────────────────────────────────────────────────────────────────


def test_client_updated_applies_the_name_and_the_inn_the_crm_owns(company):
    outcome = projections.apply_client_snapshot(client_data(name="ООО «Новое имя»", inn="999000111"))

    company.refresh_from_db()
    assert outcome.applied and company.name == "ООО «Новое имя»"
    assert company.inn == "999000111", "ИНН и реквизиты клиента ведёт CRM (ORCHESTRATOR §3 п. 16)"
    assert CrmProjectionState.objects.get(kind="client", crm_id=42).applied_at == T0


def test_an_inn_held_by_another_company_is_not_applied_but_the_name_is(company, caplog):
    make_company(name="Другая", crm_client_id=77, inn="999000111")
    with caplog.at_level(logging.WARNING):
        outcome = projections.apply_client_snapshot(client_data(name="Новое имя", inn="999000111"))
    company.refresh_from_db()
    assert outcome.applied and company.name == "Новое имя" and company.inn == "123456789"
    assert "ИНН уже у другой компании" in caplog.text


def test_a_snapshot_without_an_inn_does_not_erase_the_inn_of_the_erp(company):
    projections.apply_client_snapshot(client_data(name="Имя", inn=None))
    company.refresh_from_db()
    assert company.inn == "123456789"


def test_an_older_client_snapshot_is_not_applied(company):
    projections.apply_client_snapshot(client_data(name="Свежее", at=T0 + timedelta(minutes=5)))
    outcome = projections.apply_client_snapshot(client_data(name="Старое", at=T0))
    company.refresh_from_db()
    assert outcome.status == projections.SKIPPED_STALE and company.name == "Свежее"


def test_the_same_client_snapshot_twice_is_a_noop(company):
    first = projections.apply_client_snapshot(client_data(name="Имя"))
    again = projections.apply_client_snapshot(client_data(name="Имя"))
    assert first.applied and again.status == projections.SKIPPED_NO_CHANGE


def test_a_newer_client_snapshot_replaces_the_projection(company):
    projections.apply_client_snapshot(client_data(name="Первое"))
    outcome = projections.apply_client_snapshot(client_data(name="Второе", at=T0 + timedelta(seconds=1)))
    company.refresh_from_db()
    assert outcome.applied and company.name == "Второе"


def test_unknown_client_is_skipped_with_a_record_not_an_error(caplog):
    with caplog.at_level(logging.INFO):
        outcome = projections.apply_client_snapshot(client_data(crm_client_id=555))
    assert outcome.status == projections.SKIPPED_UNKNOWN_CLIENT
    assert "skipped_unknown_client" in caplog.text and "client.updated" in caplog.text
    assert not CrmProjectionState.objects.exists() and not Company.objects.filter(name="Новое имя").exists()


# ── contact.created / updated ──────────────────────────────────────────────────────────────────────


def test_contact_created_makes_an_erp_contact_without_the_right_to_act(company):
    outcome = projections.apply_contact_snapshot(contact_data(), "contact.created")

    assert outcome.applied
    mapping = CrmContactMapping.objects.get(crm_contact_id=58)
    contact = mapping.contact
    assert contact.company_id == company.pk and contact.name == "Иван Петров"
    assert (contact.email, contact.phone, contact.position) == (
        "ivan.petrov@example.com",
        "+998900000001",
        "Начальник снабжения",
    )
    assert (
        contact.telegram_user_id == 100000001 and contact.language == "ru" and contact.preferred_channel == "telegram"
    )
    assert contact.is_primary is True
    assert contact.can_act is False, "право действовать в Cabinet не выдаётся молча (FIX-54)"


def test_contact_updated_changes_only_the_fields_owned_by_crm(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    contact = CrmContactMapping.objects.get(crm_contact_id=58).contact
    Contact.objects.filter(pk=contact.pk).update(can_act=True)

    outcome = projections.apply_contact_snapshot(
        contact_data(at=T0 + timedelta(minutes=1), full_name="Иван П. Петров", position="Директор", phone_e164=None),
        "contact.updated",
    )

    contact.refresh_from_db()
    assert outcome.applied and contact.name == "Иван П. Петров" and contact.position == "Директор"
    assert contact.phone == ""
    assert contact.can_act is True, "права в Cabinet — своё ERP, снимком CRM не трогаются"


def test_an_older_contact_snapshot_is_not_applied(company):
    projections.apply_contact_snapshot(
        contact_data(full_name="Свежее", at=T0 + timedelta(minutes=5)), "contact.updated"
    )
    outcome = projections.apply_contact_snapshot(contact_data(full_name="Старое", at=T0), "contact.updated")
    assert outcome.status == projections.SKIPPED_STALE
    assert CrmContactMapping.objects.get(crm_contact_id=58).contact.name == "Свежее"


def test_contact_of_an_unknown_client_is_skipped(caplog):
    with caplog.at_level(logging.INFO):
        outcome = projections.apply_contact_snapshot(contact_data(crm_client_id=555), "contact.created")
    assert (
        outcome.status == projections.SKIPPED_UNKNOWN_CLIENT and not Contact.objects.filter(name="Иван Петров").exists()
    )
    assert "skipped_unknown_client" in caplog.text


def test_the_primary_contact_is_one_per_company(company):
    first = Contact.objects.filter(company=company).get()
    assert first.is_primary
    projections.apply_contact_snapshot(contact_data(is_primary=True), "contact.created")
    first.refresh_from_db()
    assert first.is_primary is False
    assert Contact.objects.filter(company=company, is_primary=True).count() == 1


def test_a_telegram_id_taken_by_another_erp_contact_is_not_stolen(company, caplog):
    Contact.objects.create(company=company, name="Другой", email="x@y.z", telegram_user_id=100000001)
    with caplog.at_level(logging.WARNING):
        outcome = projections.apply_contact_snapshot(contact_data(), "contact.created")
    contact = CrmContactMapping.objects.get(crm_contact_id=58).contact
    assert outcome.applied and contact.telegram_user_id is None
    assert Contact.objects.get(email="x@y.z").telegram_user_id == 100000001
    assert "уже у другого контакта" in caplog.text


def test_a_contact_without_telegram_in_crm_clears_it_in_the_projection(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    projections.apply_contact_snapshot(
        contact_data(at=T0 + timedelta(seconds=1), telegram_user_id=None), "contact.updated"
    )
    assert CrmContactMapping.objects.get(crm_contact_id=58).contact.telegram_user_id is None


# ── contact.deleted ────────────────────────────────────────────────────────────────────────────────


def test_contact_deleted_archives_the_contact_keeps_the_acceptance_trace_and_closes_access(company):
    from integration.tests.world import add_quote, make_deal
    from portal.models import MagicLinkToken
    from sales.models.acceptance import QuoteAcceptanceCode

    from crm.constants import QuoteStatusCode

    contact = Contact.objects.filter(company=company).first()
    contact.telegram_user_id = 424242
    contact.save(update_fields=["telegram_user_id"])
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    from portal.tests.conftest import make_portal_session

    make_portal_session(contact, company, "telegram")
    MagicLinkToken.objects.create(token_hash="h" * 64, contact=contact, expires_at=T0 + timedelta(days=3650))
    quote = add_quote(make_deal(company), 1, QuoteStatusCode.APPROVED, "1000")
    code = QuoteAcceptanceCode.objects.create(
        quote=quote,
        contact=contact,
        email=contact.email,
        code_hash="c" * 64,
        expires_at=T0 + timedelta(days=3650),
        consumed_at=T0,
    )

    outcome = projections.apply_contact_deleted(deleted_data())

    assert outcome.applied
    contact.refresh_from_db()
    assert contact.archived_at == T0 and contact.is_archived
    assert contact.can_act is False and contact.telegram_user_id is None
    assert CrmContactMapping.objects.filter(contact=contact, crm_contact_id=58).exists(), "связи остаются"
    assert QuoteAcceptanceCode.objects.filter(pk=code.pk, contact=contact).exists(), "след акцепта сохранился"
    assert not PortalSession.objects.filter(contact_id=contact.pk).exists(), "сессии сняты"
    assert not MagicLinkToken.objects.filter(contact_id=contact.pk).exists(), "ссылки входа сняты"
    state = CrmProjectionState.objects.get(kind="contact", crm_id=58)
    assert state.deleted and state.applied_at == T0


def test_an_archived_contact_cannot_sign_in_or_be_invited(company):
    from django.core import mail
    from portal.services.invitation import invite_contact_to_portal
    from portal.services.magic_link import deliver_login_link, find_login_contact

    contact = Contact.objects.filter(company=company).first()
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    assert find_login_contact(contact.email) == contact
    projections.apply_contact_deleted(deleted_data())

    contact.refresh_from_db()
    assert find_login_contact(contact.email) is None
    assert deliver_login_link(contact.pk) is False
    assert invite_contact_to_portal(contact, channel="email") == (None, "CONTACT_ARCHIVED")
    assert mail.outbox == []


def test_a_live_session_of_an_archived_contact_is_rejected_by_the_portal(company):
    from portal.tests.conftest import make_portal_session
    from rest_framework.test import APIClient

    contact = Contact.objects.filter(company=company).first()
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    session = make_portal_session(contact, company, "telegram")
    client = APIClient()
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    assert client.get("/api/portal/v1/company").status_code == 200
    # сессию снимает архивация; если бы её восстановили руками — аутентификация всё равно отказывает архивному контакту
    projections.apply_contact_deleted(deleted_data())
    session = make_portal_session(contact, company, "telegram")
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    assert client.get("/api/portal/v1/company").status_code == 401
    assert client.get("/api/portal/v1/team").status_code == 401


def test_archived_contact_is_not_in_the_team_list(company):
    from portal.tests.conftest import make_portal_session
    from rest_framework.test import APIClient

    me = Contact.objects.filter(company=company).first()
    colleague = Contact.objects.create(company=company, name="Коллега", email="k@x.uz", can_act=False)
    CrmContactMapping.objects.create(contact=colleague, crm_contact_id=59)
    session = make_portal_session(me, company, "telegram")
    client = APIClient()
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    assert {m["name"] for m in client.get("/api/portal/v1/team").json()} == {me.name, "Коллега"}
    projections.apply_contact_deleted(deleted_data(crm_contact_id=59))
    assert {m["name"] for m in client.get("/api/portal/v1/team").json()} == {me.name}


def test_late_update_after_deletion_does_not_resurrect_the_contact(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    projections.apply_contact_deleted(deleted_data(at=T0 + timedelta(minutes=2)))
    contact = CrmContactMapping.objects.get(crm_contact_id=58).contact
    assert contact.is_archived

    for moment in (T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)):  # старше и ровно в момент удаления
        outcome = projections.apply_contact_snapshot(contact_data(at=moment, full_name="Позднее"), "contact.updated")
        assert outcome.status == projections.SKIPPED_STALE
    contact.refresh_from_db()
    assert contact.is_archived and contact.name == "Иван Петров" and contact.can_act is False


def test_a_newer_snapshot_after_archiving_returns_the_contact_without_the_right_to_act(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    contact = CrmContactMapping.objects.get(crm_contact_id=58).contact
    projections.apply_contact_deleted(deleted_data(at=T0 + timedelta(minutes=1)))

    outcome = projections.apply_contact_snapshot(contact_data(at=T0 + timedelta(minutes=2)), "contact.updated")

    contact.refresh_from_db()
    assert outcome.applied and not contact.is_archived and contact.can_act is False
    assert CrmProjectionState.objects.get(kind="contact", crm_id=58).deleted is False


def test_a_contact_moved_to_another_crm_client_follows_it_to_its_company(company):
    other = make_company(name="Второй клиент", crm_client_id=43, inn="555000111")
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    contact = CrmContactMapping.objects.get(crm_contact_id=58).contact
    Contact.objects.filter(pk=contact.pk).update(can_act=True)

    outcome = projections.apply_contact_snapshot(
        contact_data(crm_client_id=43, at=T0 + timedelta(minutes=1)), "contact.updated"
    )

    contact.refresh_from_db()
    assert outcome.applied and contact.company_id == other.pk
    assert contact.can_act is False, "право действовать принадлежало прежней компании"


def test_a_contact_moved_to_an_unknown_client_stays_and_leaves_a_log(company, caplog):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    with caplog.at_level(logging.WARNING):
        projections.apply_contact_snapshot(
            contact_data(crm_client_id=9999, at=T0 + timedelta(minutes=1)), "contact.updated"
        )
    assert CrmContactMapping.objects.get(crm_contact_id=58).contact.company_id == company.pk
    assert "не передан в ERP" in caplog.text


def test_the_email_of_crm_replaces_the_one_of_the_erp(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    projections.apply_contact_snapshot(contact_data(at=T0 + timedelta(minutes=1), email=None), "contact.updated")
    assert CrmContactMapping.objects.get(crm_contact_id=58).contact.email == ""


def test_a_newer_snapshot_after_deletion_creates_the_contact_again(company):
    projections.apply_contact_deleted(deleted_data(at=T0))
    outcome = projections.apply_contact_snapshot(contact_data(at=T0 + timedelta(seconds=1)), "contact.updated")
    assert outcome.applied and CrmContactMapping.objects.filter(crm_contact_id=58).exists()
    assert CrmProjectionState.objects.get(kind="contact", crm_id=58).deleted is False


def test_repeated_deletion_is_a_noop(company):
    projections.apply_contact_snapshot(contact_data(), "contact.created")
    assert projections.apply_contact_deleted(deleted_data(at=T0 + timedelta(minutes=1))).applied
    again = projections.apply_contact_deleted(deleted_data(at=T0 + timedelta(minutes=1)))
    assert again.status == projections.SKIPPED_NO_CHANGE


def test_a_deletion_older_than_an_applied_snapshot_is_ignored(company):
    projections.apply_contact_snapshot(contact_data(at=T0 + timedelta(minutes=5)), "contact.updated")
    outcome = projections.apply_contact_deleted(deleted_data(at=T0))
    assert outcome.status == projections.SKIPPED_STALE and CrmContactMapping.objects.filter(crm_contact_id=58).exists()


def test_deleting_an_unknown_contact_only_leaves_a_tombstone():
    outcome = projections.apply_contact_deleted(deleted_data(crm_contact_id=7777))
    assert outcome.applied and "проекции не было" in outcome.detail
    assert CrmProjectionState.objects.get(kind="contact", crm_id=7777).deleted


def test_handlers_are_registered_for_the_four_crm_types():
    import integration.bus_handlers  # noqa: F401
    from rt_bus import default_registry

    for event_type in (
        "uz.railtech.crm.client.updated.v1",
        "uz.railtech.crm.contact.created.v1",
        "uz.railtech.crm.contact.updated.v1",
        "uz.railtech.crm.contact.deleted.v1",
    ):
        assert default_registry.match(event_type), event_type
    assert not default_registry.match("uz.railtech.crm.lead.created.v1")


def test_snapshots_are_not_mutated(company):
    data = client_data()
    before = copy.deepcopy(data)
    projections.apply_client_snapshot(data)
    assert data == before
