"""СУЩ-2.7 (ADR-0028 п. 6): реквизиты компании-контрагента ведёт ERP — снимок `company.updated` уходит в CRM.

Снимок пишет сигнал модели в outbox той же транзакции: при создании и при изменении названия, ИНН, рег. номера, страны или
юридического адреса — только у компании, связанной с клиентом CRM; своя компания и правка других полей — без события.
Откат транзакции — события нет.
"""

from __future__ import annotations

import pytest
from django.db import transaction
from integration.models import CrmClientMapping
from integration.tests.bus_support import published
from integration.tests.world import make_company
from parties.models import Company

from core.models import Country

pytestmark = pytest.mark.django_db

SHORT = "company.updated"


def test_a_change_of_requisites_of_a_crm_company_publishes_a_full_snapshot():
    company = make_company(name="ООО Клиент", crm_client_id=42, inn="123456789")
    uz, _ = Country.objects.get_or_create(code="UZ", defaults={"name": "Узбекистан"})
    before = len(published(SHORT))

    company.name = "ООО «Новое имя»"
    company.country = uz
    company.legal_address = "  Ташкент  "
    company.save()

    events = published(SHORT)
    assert len(events) == before + 1
    data = events[-1]["data"]
    assert data["erp_company_id"] == company.pk
    assert data["company"] == {
        "name": "ООО «Новое имя»",
        "inn": "123456789",
        "registration_number": None,
        "country": "UZ",
        "legal_address": "Ташкент",
        "do_not_work": None,
        "is_test": False,
        "updated_at": data["company"]["updated_at"],
    }


def test_other_fields_and_unlinked_companies_publish_nothing():
    company = make_company(name="ООО Клиент", crm_client_id=42, inn="123456789")
    before = len(published(SHORT))
    company.phone = "+998901112233"
    company.save()
    stranger = Company.objects.create(name="Без клиента CRM", inn="300000999")
    stranger.name = "Новое имя"
    stranger.save()
    assert len(published(SHORT)) == before


def test_the_snapshot_goes_out_once_the_mapping_exists():
    company = Company.objects.create(name="Передаётся", inn="300000555")
    CrmClientMapping.objects.create(crm_client_id=77, company=company)
    before = len(published(SHORT))
    company.inn = "300000556"
    company.save(update_fields=["inn", "updated_at"])
    assert len(published(SHORT)) == before + 1


def test_a_rolled_back_change_leaves_no_event():
    company = make_company(name="ООО Клиент", crm_client_id=42, inn="123456789")
    before = len(published(SHORT))
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            company.name = "Откат"
            company.save()
            raise RuntimeError("rollback")
    assert len(published(SHORT)) == before
