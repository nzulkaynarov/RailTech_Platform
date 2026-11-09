"""FX-9: контакт отключил Telegram для группы в кабинете — событие шины называет его, бот CRM ему не пишет."""

import datetime

import pytest
from django.utils import timezone
from integration.models import CrmClientMapping
from integration.services.events import muted_telegram_user_ids, publish_invoice_event
from integration.tests import bus_support
from parties.models import Company, Contact

from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Invoice, InvoiceStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def company(db):
    item = Company.objects.create(name="ООО Настройки", inn="223456789")
    CrmClientMapping.objects.create(company=item, crm_client_id=77)
    return item


def contact(company, tg, settings=None, **extra):
    return Contact.objects.create(
        company=company,
        name=f"К{tg}",
        email=f"c{tg}@settings.example",
        telegram_user_id=tg,
        notification_settings=settings or {},
        **extra,
    )


def test_only_contacts_that_turned_the_group_off_are_named(company):
    contact(company, 1001, {"money": {"telegram": False}})
    contact(company, 1002, {"money": {"telegram": True}})
    contact(company, 1003, {"documents": {"telegram": False}})
    contact(company, 1004)
    assert muted_telegram_user_ids(company.pk, "invoice.issued") == [1001]
    assert muted_telegram_user_ids(company.pk, "act.issued") == [1003]
    assert muted_telegram_user_ids(company.pk, "delivery.status_changed") == []


def test_archived_contact_and_event_without_group_are_not_named(company):
    contact(company, 1005, {"money": {"telegram": False}}, archived_at=timezone.now())
    assert muted_telegram_user_ids(company.pk, "invoice.issued") == []
    contact(company, 1006, {"money": {"telegram": False}})
    assert muted_telegram_user_ids(company.pk, "request.created") == []


def _invoice(company):
    stage = DealStage.objects.get_or_create(code=DealStageCode.DRAFT, defaults={"name": "Черновик"})[0]
    deal = Deal.objects.create(company=company, stage=stage)
    status = InvoiceStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выставлен"})[0]
    return Invoice.objects.create(deal=deal, number="INV-FX9", status=status, due_date=datetime.date(2026, 12, 1))


def test_event_passes_the_schema_and_carries_the_list(company):
    contact(company, 1001, {"money": {"telegram": False}})
    publish_invoice_event("invoice.issued", _invoice(company))
    assert bus_support.only("invoice.issued")["data"]["telegram_muted_user_ids"] == [1001]


def test_event_is_unchanged_when_nobody_opted_out(company):
    contact(company, 1002)
    publish_invoice_event("invoice.issued", _invoice(company))
    assert "telegram_muted_user_ids" not in bus_support.only("invoice.issued")["data"]
