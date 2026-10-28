"""Передача клиента из CRM (`POST /clients/handoff`): идемпотентность, ИНН, события, согласие (FIX-31; I-4, I-5, I-20).

Каждый пункт задачи — свой тест: поиск по `crm_client_id` и ИНН, 409 `INN_CONFLICT` без побочных эффектов,
сопоставление до сделки, `request.created(source=crm)` и `invite.sent`, честный `sent_via`, согласие на компании,
повтор без второй сделки и без вторых событий, две передачи одного клиента одновременно.
"""

from __future__ import annotations

import copy
import threading
import uuid

import pytest
from django.core import mail
from django.db import connections
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.tests import bus_support
from parties.models import Company, CompanyType, Contact
from rest_framework.test import APIClient

from crm.constants import DealStageCode
from crm.models import ActivityLog, Deal

SERVICE_TOKEN = "test-crm-to-erp-token"
URL = "/api/integration/v1/clients/handoff"
CONSENT_AT = "2026-10-01T09:30:00+05:00"


@pytest.fixture(autouse=True)
def integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.CABINET_URL = "http://cabinet.localhost"
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})


@pytest.fixture
def api():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def payload(crm_client_id=1001, inn="123456789", channels=("email",), create_request=True, email="ivan@client.uz"):
    return {
        "crm_client_id": crm_client_id,
        "crm_lead_id": 501,
        "company": {"name": "ООО Рельсы Тест", "inn": inn, "segment": "enterprise", "language": "ru"},
        "contacts": [
            {
                "crm_contact_id": crm_client_id * 10 + 1,
                "name": "Иван Иванов",
                "phone": "+998901234567",
                "email": email,
                "telegram_user_id": 12345678,
                "language": "ru",
                "is_primary": True,
                "preferred_channel": "both",
            }
        ],
        "need": {"summary": "Поставка рельсов Р65, 500 тонн", "product_interest": ["Рельс Р65"], "attachments": []},
        "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
        "consent": {"given_at": CONSENT_AT, "version": "2026-09"},
        "create_request": create_request,
        "invite": {"channels": list(channels)},
    }


def handoff(api, body, key=None):
    return api.post(URL, body, format="json", HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


def events(event_type=None):
    """Опубликованные на шину события (конверты) — все или одного короткого типа (`request.created`)."""
    return bus_support.published(event_type)


# ─── Повтор: те же идентификаторы, без второй сделки и без вторых событий ──────────────────────────


@pytest.mark.django_db
def test_repeat_with_same_crm_client_id_returns_200_and_same_ids_without_new_objects_or_events(api):
    first = handoff(api, payload())
    assert first.status_code == 201
    deals, companies, contacts = Deal.objects.count(), Company.objects.count(), Contact.objects.count()
    sent_events = len(events())
    emails = len(mail.outbox)

    again = handoff(api, payload())  # другой Idempotency-Key: повтор после таймаута, ключ потерян

    assert again.status_code == 200
    assert again.json()["erp_company_id"] == first.json()["erp_company_id"]
    assert again.json()["erp_request_id"] == first.json()["erp_request_id"]
    assert (Deal.objects.count(), Company.objects.count(), Contact.objects.count()) == (deals, companies, contacts)
    assert len(events()) == sent_events, "повтор не должен рождать события"
    assert len(mail.outbox) == emails, "повтор не должен слать второе приглашение"


@pytest.mark.django_db
def test_repeat_reports_only_what_really_went_out(api):
    first = handoff(api, payload(channels=("email", "telegram")))
    again = handoff(api, payload(channels=("email", "telegram")))
    assert first.json()["invite"]["sent_via"] == ["email", "telegram"]
    assert again.json()["invite"]["sent_via"] == ["email", "telegram"]
    assert again.json()["invite"]["error"] is None


@pytest.mark.django_db
def test_company_is_found_by_crm_client_id_even_if_inn_changed_in_crm(api):
    first = handoff(api, payload(inn="123456789"))
    again = handoff(api, payload(inn="987654321"))  # менеджер поправил ИНН в CRM — это та же компания
    assert again.status_code == 200
    assert again.json()["erp_company_id"] == first.json()["erp_company_id"]
    assert Company.objects.count() == 1


# ─── ИНН ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_inn_of_another_crm_client_is_409_inn_conflict_and_nothing_is_created(api):
    first = handoff(api, payload(crm_client_id=1001, inn="123456789"))
    assert first.status_code == 201
    before = (
        Company.objects.count(),
        Contact.objects.count(),
        Deal.objects.count(),
        CrmClientMapping.objects.count(),
        CrmContactMapping.objects.count(),
        len(events()),
        len(mail.outbox),
    )

    conflict = handoff(api, payload(crm_client_id=2002, inn="123456789", email="other@client.uz"))

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "INN_CONFLICT"}
    after = (
        Company.objects.count(),
        Contact.objects.count(),
        Deal.objects.count(),
        CrmClientMapping.objects.count(),
        CrmContactMapping.objects.count(),
        len(events()),
        len(mail.outbox),
    )
    assert after == before
    company = Company.objects.get(pk=first.json()["erp_company_id"])
    assert company.crm_client_mapping.crm_client_id == 1001, "ничего не переписывается"


@pytest.mark.django_db
def test_inn_conflict_is_not_replayed_as_success_and_not_stored_as_idempotent_result(api):
    handoff(api, payload(crm_client_id=1001, inn="123456789"))
    key = str(uuid.uuid4())
    assert handoff(api, payload(crm_client_id=2002, inn="123456789"), key).status_code == 409
    # тот же ключ, тот же вызов — снова 409, а не «закешированный успех»
    assert handoff(api, payload(crm_client_id=2002, inn="123456789"), key).status_code == 409


@pytest.mark.django_db
def test_existing_company_without_crm_link_is_found_by_inn_and_linked(api):
    existing = Company.objects.create(name="ООО Заведена в ERP", inn="555666777")
    Contact.objects.create(company=existing, name="Старый контакт", email="ivan@client.uz")
    contacts_before = Contact.objects.count()

    resp = handoff(api, payload(crm_client_id=3003, inn="555666777"))

    assert resp.status_code == 201
    assert resp.json()["erp_company_id"] == existing.pk
    assert Company.objects.count() == 1, "второй компании с тем же ИНН не появилось"
    assert CrmClientMapping.objects.get(crm_client_id=3003).company_id == existing.pk
    # контакт с тем же e-mail не задваивается, а получает сопоставление
    assert Contact.objects.count() == contacts_before
    assert CrmContactMapping.objects.get(crm_contact_id=30031).contact.email == "ivan@client.uz"
    assert Deal.objects.filter(company=existing).count() == 1


def _linked_by_inn(api, **kwargs):
    """Компания заведена сотрудником (со своей старой сделкой и контактом), клиент CRM пришёл с её ИНН."""
    existing = Company.objects.create(name="ООО Заведена в ERP", inn="555666777")
    staff_contact = Contact.objects.create(company=existing, name="Сотрудник клиента", email="staff@client.uz")
    old_deal = Deal.objects.create(company=existing, title="Старая сделка сотрудника")
    resp = handoff(api, payload(crm_client_id=3003, inn="555666777", **kwargs))
    return existing, staff_contact, old_deal, resp


@pytest.mark.django_db
def test_repeat_after_inn_link_returns_the_request_made_by_the_handoff_not_the_oldest_deal(api):
    existing, _staff, old_deal, first = _linked_by_inn(api)
    handoff_deal = Deal.objects.exclude(pk=old_deal.pk).get(company=existing)
    assert first.json()["erp_request_id"] == handoff_deal.pk != old_deal.pk

    changed = payload(crm_client_id=3003, inn="555666777", email="new@client.uz")  # другое тело, другой ключ
    again = handoff(api, changed)

    assert again.status_code == 200
    assert again.json()["erp_request_id"] == handoff_deal.pk
    assert again.json()["erp_company_id"] == existing.pk


@pytest.mark.django_db
def test_repeat_without_request_does_not_pick_up_a_staff_deal(api):
    existing, _staff, _old, first = _linked_by_inn(api, create_request=False)
    assert first.json()["erp_request_id"] is None

    again = handoff(api, payload(crm_client_id=3003, inn="555666777", create_request=False))

    assert again.json()["erp_request_id"] is None, "сделка сотрудника — не заявка передачи"


@pytest.mark.django_db
def test_inn_link_gives_new_contacts_no_right_to_act_and_sends_no_invite(api):
    """Опечатка в ИНН не должна отдать постороннему чужие КП, договоры и счета (Q-FIX31-5)."""
    existing, staff_contact, _old, resp = _linked_by_inn(api, channels=("email", "telegram"))

    assert resp.status_code == 201
    assert resp.json()["invite"]["sent_via"] == []
    assert resp.json()["invite"]["error"] == "COMPANY_LINKED_BY_INN"
    new_contact = CrmContactMapping.objects.get(crm_contact_id=30031).contact
    assert new_contact.company_id == existing.pk
    assert new_contact.can_act is False
    assert new_contact.invited_at is None
    assert len(mail.outbox) == 0
    assert len(events("invite.sent")) == 0
    # заявка и request.created на месте — передача не теряется
    assert len(events("request.created")) == 1
    log = ActivityLog.objects.get(event_code="company.linked_by_inn")
    assert log.company_id == existing.pk
    assert "проверьте контакты" in log.action
    assert log.event_params["crm_client_id"] == 3003


@pytest.mark.django_db
def test_inn_link_with_matching_email_keeps_the_existing_contact_untouched(api):
    existing = Company.objects.create(name="ООО Заведена в ERP", inn="555666777")
    staff_contact = Contact.objects.create(company=existing, name="Старый", email="ivan@client.uz", can_act=True)

    resp = handoff(api, payload(crm_client_id=3003, inn="555666777"))

    staff_contact.refresh_from_db()
    assert staff_contact.can_act is True and staff_contact.invited_at is None
    assert resp.json()["invite"]["sent_via"] == []
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_inn_link_repeat_does_not_report_an_old_staff_invite_as_sent(api):
    existing = Company.objects.create(name="ООО Заведена в ERP", inn="555666777")
    Contact.objects.create(
        company=existing, name="Старый", email="ivan@client.uz", is_primary=True, invited_at=timezone.now()
    )
    handoff(api, payload(crm_client_id=3003, inn="555666777"))

    again = handoff(api, payload(crm_client_id=3003, inn="555666777", email="x@client.uz"))

    assert again.json()["invite"]["sent_via"] == []


@pytest.mark.django_db
def test_new_company_path_is_unchanged_contacts_can_act_and_are_invited(api):
    resp = handoff(api, payload())
    contact = CrmContactMapping.objects.get(crm_contact_id=10011).contact
    assert contact.can_act is True
    assert contact.invited_at is not None
    assert resp.json()["invite"]["sent_via"] == ["email"]
    assert ActivityLog.objects.filter(event_code="company.linked_by_inn").count() == 0


@pytest.mark.django_db
def test_two_crm_contacts_with_one_email_do_not_break_the_handoff(api):
    body = payload()
    second = copy.deepcopy(body["contacts"][0])
    second.update(crm_contact_id=99902, name="Второй с тем же e-mail", is_primary=False, telegram_user_id=None)
    body["contacts"].append(second)

    resp = handoff(api, body)

    assert resp.status_code == 201
    assert Contact.objects.filter(email="ivan@client.uz").count() == 1
    assert CrmContactMapping.objects.count() == 1, "контакт уже сопоставлен — второй номер пропущен"


@pytest.mark.django_db
def test_already_mapped_crm_contact_id_is_skipped_not_a_500(api):
    other = Company.objects.create(name="Чужая", inn="111222333")
    foreign = Contact.objects.create(company=other, name="Чужой контакт", email="other@client.uz")
    CrmContactMapping.objects.create(crm_contact_id=10011, contact=foreign)

    resp = handoff(api, payload())

    assert resp.status_code == 201
    assert CrmContactMapping.objects.get(crm_contact_id=10011).contact_id == foreign.pk


@pytest.mark.django_db
def test_telegram_account_bound_to_another_contact_is_not_hijacked_and_does_not_break_handoff(api):
    a = handoff(api, payload(crm_client_id=1, inn=""))
    b = handoff(api, payload(crm_client_id=2, inn="", email="b@client.uz"))  # тот же telegram_user_id
    assert (a.status_code, b.status_code) == (201, 201)
    owner = Contact.objects.get(telegram_user_id=12345678)
    assert owner.company_id == a.json()["erp_company_id"]


@pytest.mark.django_db
def test_companies_without_inn_do_not_collide(api):
    a = handoff(api, payload(crm_client_id=1, inn=""))
    b = handoff(api, payload(crm_client_id=2, inn="", email="b@client.uz"))
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["erp_company_id"] != b.json()["erp_company_id"]
    assert Company.objects.filter(inn__isnull=True).count() == 2


# ─── Сопоставление до сделки, события ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_mapping_exists_before_deal_is_created(api, monkeypatch):
    seen = {}
    original = Deal.save

    def spy(self, *args, **kwargs):
        if self._state.adding:
            seen["mapped"] = CrmClientMapping.objects.filter(crm_client_id=1001).exists()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Deal, "save", spy)
    assert handoff(api, payload()).status_code == 201
    assert seen == {"mapped": True}


@pytest.mark.django_db
def test_request_created_is_emitted_once_with_source_crm_and_deal_in_request_stage(api):
    resp = handoff(api, payload())
    deal = Deal.objects.get(pk=resp.json()["erp_request_id"])

    created = list(events("request.created"))
    assert len(created) == 1
    body = created[0]["data"]
    assert body["crm_client_id"] == 1001
    assert body["erp_company_id"] == deal.company_id
    assert body["payload"]["source"] == "crm"
    assert body["payload"]["erp_request_id"] == deal.pk
    assert body["payload"]["summary"] == "Поставка рельсов Р65, 500 тонн"
    assert body["actor"] == {"type": "staff", "name": "Менеджер Продаж"}
    # C1-G-7: отправитель письма EDS — компания и основной контакт, менеджер — ответственный передачи из CRM
    assert {k: body["payload"][k] for k in ("company_name", "company_inn", "contact_name", "manager_crm_user_id")} == {
        "company_name": "ООО Рельсы Тест",
        "company_inn": "123456789",
        "contact_name": "Иван Иванов",
        "manager_crm_user_id": 101,
    }
    assert body["deal"]["erp_deal_id"] == deal.pk
    assert body["deal"]["stage"] == "request"
    assert body["deal"]["amount"] is None
    assert deal.stage.code == DealStageCode.DRAFT, "стадия — через stages.py, не code='request'"


@pytest.mark.django_db
def test_invite_sent_reaches_crm_with_only_channels_that_really_went_out(api):
    resp = handoff(api, payload(channels=("telegram", "email")))

    assert resp.json()["invite"]["sent_via"] == ["email", "telegram"]
    sent = list(events("invite.sent"))
    assert len(sent) == 1, "`invite.sent` — только за ушедшее письмо; Telegram — отдельное событие боту"
    assert sent[0]["data"]["crm_client_id"] == 1001
    assert sent[0]["data"]["payload"]["channels"] == ["email"]
    requested = list(events("invite.requested"))
    assert len(requested) == 1
    assert requested[0]["data"]["payload"] == {
        "channel": "telegram",
        "erp_contact_id": Contact.objects.get().pk,
        "crm_contact_id": 10011,
        "language": "ru",
    }
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_telegram_only_invite_goes_to_the_crm_bot_not_pretended(api):
    """D1-9: канал `telegram` доставляет бот CRM по событию; ERP не пишет в Telegram сама и письма не шлёт."""
    resp = handoff(api, payload(channels=("telegram",)))

    assert resp.status_code == 201
    assert resp.json()["invite"]["sent_via"] == ["telegram"]
    assert resp.json()["invite"]["error"] is None
    assert len(events("invite.requested")) == 1
    assert len(events("invite.sent")) == 0
    assert len(mail.outbox) == 0
    contact = Contact.objects.get()
    assert contact.invited_at is not None
    # заявка и сопоставление при этом на месте
    assert resp.json()["erp_request_id"] is not None
    assert len(events("request.created")) == 1


@pytest.mark.django_db
def test_telegram_invite_without_telegram_account_is_an_error_with_a_code(api):
    body = payload(channels=("telegram",))
    body["contacts"][0]["telegram_user_id"] = None
    resp = handoff(api, body)

    assert resp.status_code == 201
    assert resp.json()["invite"]["sent_via"] == []
    assert resp.json()["invite"]["error"] == "CONTACT_TELEGRAM_REQUIRED"
    assert len(events("invite.requested")) == 0
    assert Contact.objects.get().invited_at is None


@pytest.mark.django_db
def test_contact_without_email_gets_no_invite_but_handoff_succeeds(api):
    body = payload(channels=("email",), email="")
    resp = handoff(api, body)
    assert resp.status_code == 201
    assert resp.json()["invite"]["sent_via"] == []
    assert resp.json()["invite"]["error"] == "CONTACT_EMAIL_REQUIRED"
    assert len(events("invite.sent")) == 0


@pytest.mark.django_db
def test_without_create_request_no_deal_and_no_request_event(api):
    resp = handoff(api, payload(create_request=False))
    assert resp.status_code == 201
    assert resp.json()["erp_request_id"] is None
    assert Deal.objects.count() == 0
    assert len(events("request.created")) == 0
    assert len(events("invite.sent")) == 1


# ─── Согласие ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_consent_is_stored_on_company_as_received(api):
    resp = handoff(api, payload())
    company = Company.objects.get(pk=resp.json()["erp_company_id"])
    assert company.consent_version == "2026-09"
    assert company.consent_given_at is not None
    assert company.consent_given_at.isoformat() == "2026-10-01T04:30:00+00:00"


@pytest.mark.django_db
def test_repeat_does_not_rewrite_stored_consent(api):
    first = handoff(api, payload())
    changed = payload()
    changed["consent"] = {"given_at": "2026-10-15T10:00:00+05:00", "version": "2026-10"}
    handoff(api, changed)
    company = Company.objects.get(pk=first.json()["erp_company_id"])
    assert company.consent_version == "2026-09"


@pytest.mark.django_db
def test_consent_is_required_by_contract(api):
    body = payload()
    del body["consent"]
    assert handoff(api, body).status_code == 422


# ─── Идемпотентность по заголовку ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_same_key_same_body_replays_first_answer_without_second_effects(api):
    key = str(uuid.uuid4())
    first = handoff(api, payload(), key)
    events_count = len(events())
    replay = handoff(api, payload(), key)
    assert replay.status_code == first.status_code == 201
    assert replay.json() == first.json()
    assert len(events()) == events_count


# ─── Параллельные передачи ─────────────────────────────────────────────────────────────────────────


def _run_parallel(api_token, bodies):
    barrier = threading.Barrier(len(bodies))
    results = [None] * len(bodies)
    errors = []

    def worker(index, body):
        try:
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_token}")
            barrier.wait(timeout=10)
            results[index] = client.post(
                URL, copy.deepcopy(body), format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
            )
        except Exception as exc:  # noqa: BLE001 — упавший поток должен провалить тест, а не повиснуть
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, b)) for i, b in enumerate(bodies)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    return results


@pytest.mark.django_db(transaction=True)
def test_two_parallel_handoffs_of_one_client_make_one_company_one_deal_and_one_set_of_events():
    results = _run_parallel(SERVICE_TOKEN, [payload(), payload()])

    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json()["erp_company_id"] == results[1].json()["erp_company_id"]
    assert results[0].json()["erp_request_id"] == results[1].json()["erp_request_id"]
    assert Company.objects.count() == 1
    assert Deal.objects.count() == 1
    assert CrmClientMapping.objects.count() == 1
    assert len(events("request.created")) == 1
    assert len(events("invite.sent")) == 1
    assert len(mail.outbox) == 1


@pytest.mark.django_db(transaction=True)
def test_two_parallel_handoffs_of_different_clients_with_same_inn_one_wins_other_gets_409():
    results = _run_parallel(
        SERVICE_TOKEN,
        [payload(crm_client_id=1001, inn="777888999"), payload(crm_client_id=2002, inn="777888999", email="b@c.uz")],
    )

    assert sorted(r.status_code for r in results) == [201, 409]
    assert [r.json() for r in results if r.status_code == 409] == [{"detail": "INN_CONFLICT"}]
    assert Company.objects.filter(inn="777888999").count() == 1
    assert CrmClientMapping.objects.count() == 1
    assert Deal.objects.count() == 1
