"""Правки по ревью B3: реквизиты ведёт CRM (только чтение в ERP), ротация секрета сопряжения, напоминания об оплате.

* название и ИНН компании, связанной с клиентом CRM, API ERP не правит: internal — 400, portal — 422
  `REQUISITES_MANAGED_BY_CRM` (ORCHESTRATOR §3 п. 16); несвязанная компания правится как раньше;
* прежний секрет сопряжения принимается на переходный срок ротации, и вывод секрета пары шины (L12) не даёт 401;
* `send_payment_reminders`: на каждый счёт свой atomic, письмо — после коммита, сбой одного счёта не останавливает остальные.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from integration.bus import derive_pair_secret, pair_secrets
from integration.models import CredentialSlot, ServiceCredential
from integration.services import credentials, pairing
from integration.tests import bus_support
from integration.tests.world import make_company
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CustomUser

pytestmark = pytest.mark.django_db


# ── Реквизиты ведёт CRM ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_api():
    user = CustomUser.objects.create_user(
        email="root@req.test", username="root_req", password="x", is_staff=True, is_superuser=True
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def test_internal_api_rejects_a_change_of_name_or_inn_of_a_crm_company(admin_api):
    company = make_company(name="ООО CRM", crm_client_id=42, inn="123456789")
    for body in ({"inn": "987654321"}, {"name": "Другое имя"}, {"name": "Другое имя", "legal_address": "x"}):
        response = admin_api.patch(f"/api/v1/accounts/companies/{company.pk}/", body, format="json")
        assert response.status_code == 400, response.content
        assert response.json()["detail"] == "REQUISITES_MANAGED_BY_CRM"
        assert set(response.json()["fields"]) <= {"name", "inn"}
    company.refresh_from_db()
    assert (company.name, company.inn, company.legal_address) == ("ООО CRM", "123456789", "")


def test_internal_api_allows_other_fields_and_unchanged_values(admin_api):
    company = make_company(name="ООО CRM", crm_client_id=42, inn="123456789")
    response = admin_api.patch(
        f"/api/v1/accounts/companies/{company.pk}/",
        {"legal_address": "г. Ташкент", "name": "ООО CRM", "inn": "123456789"},
        format="json",
    )
    assert response.status_code == 200, response.content
    company.refresh_from_db()
    assert company.legal_address == "г. Ташкент"


def test_internal_api_still_edits_a_company_without_crm(admin_api):
    company = make_company(name="Своя", crm_client_id=None, inn="123456789")
    response = admin_api.patch(f"/api/v1/accounts/companies/{company.pk}/", {"inn": "987654321"}, format="json")
    assert response.status_code == 200, response.content
    company.refresh_from_db()
    assert company.inn == "987654321"


# ── Ротация секрета сопряжения ───────────────────────────────────────────────────────────────────


def _rotate(current, **new):
    return pairing.rotate(
        current,
        crm_to_erp_token=new["crm"],
        erp_to_crm_token=new["erp"],
        webhook_secret=new["webhook"],
    )


def test_rotation_keeps_the_previous_webhook_secret_for_the_overlap(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = ["env-token"]
    settings.ERP_WEBHOOK_SECRET = "env-webhook"
    _rotate("env-token", crm="n" * 40, erp="m" * 40, webhook="first-" + "w" * 40)
    first = "first-" + "w" * 40
    # первая ротация по .env: прежним был секрет из окружения
    assert credentials.webhook_secrets() == [first, "env-webhook"]
    assert pair_secrets("crm", "erp") == [
        derive_pair_secret(first, "crm", "erp"),
        derive_pair_secret("env-webhook", "crm", "erp"),
    ]
    assert pair_secrets("erp", "crm")[0] == derive_pair_secret(first, "erp", "crm"), "подписывает новый"

    second = "second-" + "w" * 40
    _rotate("n" * 40, crm="a" * 40, erp="b" * 40, webhook=second)
    assert credentials.webhook_secrets() == [second, first]


def test_the_previous_webhook_secret_expires_with_the_grace_period(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = ["env-token"]
    settings.ERP_WEBHOOK_SECRET = "env-webhook"
    _rotate("env-token", crm="n" * 40, erp="m" * 40, webhook="first-" + "w" * 40)
    ServiceCredential.objects.filter(slot=CredentialSlot.WEBHOOK_SECRET_PREVIOUS).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert credentials.webhook_secrets() == ["first-" + "w" * 40]


def test_a_repeated_pairing_drops_the_previous_secret(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = ["env-token"]
    settings.ERP_WEBHOOK_SECRET = "env-webhook"
    _rotate("env-token", crm="n" * 40, erp="m" * 40, webhook="first-" + "w" * 40)
    pairing._replace_credentials("x" * 40, "y" * 40, "z" * 40)
    assert credentials.webhook_secrets() == ["z" * 40]


def test_events_signed_before_the_rotation_are_still_accepted_after_it(settings):
    """Ротация без 401: CRM ещё подписывает прежним секретом пары — ERP принимает его на переходный срок."""
    from integration.tests.test_bus_wiring import crm_event, signed_post

    settings.SERVICE_TOKEN_CRM_TO_ERP = ["env-token"]
    settings.ERP_WEBHOOK_SECRET = "env-webhook"
    _rotate("env-token", crm="n" * 40, erp="m" * 40, webhook="first-" + "w" * 40)
    old_pair = derive_pair_secret("env-webhook", "crm", "erp")
    new_pair = derive_pair_secret("first-" + "w" * 40, "crm", "erp")
    assert signed_post(crm_event("client.updated"), secret=old_pair).status_code == 200
    assert signed_post(crm_event("client.updated"), secret=new_pair).status_code == 200
    assert signed_post(crm_event("client.updated"), secret="x" * 64).status_code == 401


# ── send_payment_reminders ───────────────────────────────────────────────────────────────────────


def test_a_publication_failure_of_one_invoice_does_not_stop_the_others(django_capture_on_commit_callbacks):
    from integration.services import events
    from integration.tests import world as w

    from crm.constants import InvoiceStatusCode
    from crm.models import Invoice
    from crm.tasks import send_payment_reminders

    company = make_company(crm_client_id=42)
    deal = w.make_deal(company)
    past = timezone.localdate() - timedelta(days=30)
    first = w.add_invoice(deal, InvoiceStatusCode.ISSUED, "1000", "0", due=past)
    second = w.add_invoice(deal, InvoiceStatusCode.ISSUED, "2000", "0", due=past)
    real = events.publish_invoice_event
    sent = []

    def flaky(event_type, invoice, *args, **kwargs):
        if invoice.pk == first.pk:
            raise RuntimeError("шина недоступна")
        return real(event_type, invoice, *args, **kwargs)

    with (
        patch.object(events, "publish_invoice_event", flaky),
        patch("crm.services.deal_emails.email_payment_reminder", lambda invoice: sent.append(invoice.pk) or 1),
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(RuntimeError, match="не обработано счетов — 1, обработано — 1"),
    ):
        send_payment_reminders()

    first, second = Invoice.objects.get(pk=first.pk), Invoice.objects.get(pk=second.pk)
    assert first.payment_reminder_sent_at is None, "отметка первого счёта откатилась вместе с публикацией"
    assert second.payment_reminder_sent_at is not None
    assert sent == [second.pk], "письмо — только по счёту, у которого отметка и событие зафиксированы"
    published = bus_support.published("invoice.overdue")
    assert [e["data"]["payload"]["erp_invoice_id"] for e in published] == [second.pk]


def test_the_failed_invoice_is_retried_on_the_next_run(django_capture_on_commit_callbacks):
    from integration.tests import world as w

    from crm.constants import InvoiceStatusCode
    from crm.tasks import send_payment_reminders

    company = make_company(crm_client_id=42)
    invoice = w.add_invoice(
        w.make_deal(company), InvoiceStatusCode.ISSUED, "1000", "0", due=timezone.localdate() - timedelta(days=30)
    )
    with patch("integration.services.events.publish_invoice_event", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            send_payment_reminders()
    invoice.refresh_from_db()
    assert invoice.payment_reminder_sent_at is None

    with (
        patch("crm.services.deal_emails.email_payment_reminder", return_value=1),
        django_capture_on_commit_callbacks(execute=True),
    ):
        assert send_payment_reminders() == {"reminded": 1}
    assert len(bus_support.published("invoice.overdue")) == 1
