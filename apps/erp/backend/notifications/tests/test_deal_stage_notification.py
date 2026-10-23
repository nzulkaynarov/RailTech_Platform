"""Уведомление клиенту о смене стадии сделки (FIX-54): прежнюю стадию запоминает `notifications.signals`, а не вебхуки.

До B3 признак `_prev_stage_id` ставил сигнал приложения интеграции вместе с вебхуками ERP → CRM; события теперь публикует
сервисный слой на шину rt_bus (`crm/services/deals.py`), а уведомление клиенту осталось сигналом `post_save` сделки.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from integration.tests import world

from core.models import Notification
from crm.constants import DealStageCode
from crm.models import DealStage

pytestmark = pytest.mark.django_db


@pytest.fixture
def deal():
    return world.make_deal(world.make_company())


def test_deal_stage_change_notifies_the_client_once(deal, django_user_model):
    client = django_user_model.objects.create_user(username="client54", password="x")
    deal.client = client
    deal.save(update_fields=["client"])
    assert not Notification.objects.filter(user=client, event_code="deal.stage_changed").exists()
    deal.stage = DealStage.objects.get_or_create(code=DealStageCode.CALCULATING, defaults={"name": "Расчёт"})[0]
    deal.save()
    assert Notification.objects.filter(user=client, event_code="deal.stage_changed").count() == 1
    deal.save()  # стадия не менялась — второго уведомления нет
    assert Notification.objects.filter(user=client, event_code="deal.stage_changed").count() == 1


def test_save_of_other_fields_reads_nothing_before_the_update(deal):
    with CaptureQueriesContext(connection) as ctx:
        deal.save(update_fields=["title"])
    assert len(ctx) == 1, [q["sql"] for q in ctx.captured_queries]
    assert ctx.captured_queries[0]["sql"].lstrip().startswith("UPDATE")


def test_stage_change_reads_the_previous_row_once(deal):
    new_stage = DealStage.objects.get_or_create(code=DealStageCode.RFQ_OPEN, defaults={"name": "RFQ"})[0]
    deal.client = None
    deal.stage = new_stage
    with CaptureQueriesContext(connection) as ctx:
        deal.save()
    reads = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().startswith("SELECT") and f'WHERE "sales_deal"."id" = {deal.pk}' in q["sql"]
    ]
    assert len(reads) == 1, reads
