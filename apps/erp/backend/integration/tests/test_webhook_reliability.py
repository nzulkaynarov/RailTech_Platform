"""Надёжность доставки вебхуков ERP → CRM (FIX-33, находки I-7, I-10).

* журнал доставок в админке и действие «Повторить» (только суперпользователь, с подтверждением и причиной);
* задача Beat подбирает зависшие `PENDING` и ставит повтор, не трогая те, что ждут своего ретрая;
* `visibility_timeout` брокера не меньше самого длинного интервала повторов (иначе Redis вернёт
  отложенную на 2–24 ч задачу в очередь через час и доставка задвоится);
* событие без секрета не теряется: строка остаётся `PENDING` и уходит, когда секрет появился;
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse
from django.utils import timezone
from integration.models import CrmClientMapping, IntegrationWebhookEvent, WebhookEventStatus
from integration.services.webhooks import emit_event
from integration.tasks import (
    RETRY_DELAYS,
    STUCK_GRACE,
    deliver_webhook_event,
    redeliver_event,
    requeue_stuck_webhook_events,
)
from parties.models import Company

from accounts.models import CustomUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def mapped_company():
    company = Company.objects.create(name="ООО Надёжность", inn="223456789")
    CrmClientMapping.objects.create(company=company, crm_client_id=77)
    return company


def _event(company, **fields) -> IntegrationWebhookEvent:
    event = emit_event("invite.sent", company.id, {"channels": ["email"]}, send_async=False)
    assert event is not None
    for name, value in fields.items():
        setattr(event, name, value)
    event.save()
    return event


def _created_ago(event, **delta) -> None:
    IntegrationWebhookEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(**delta))


# ─── visibility_timeout и расписание Beat ─────────────────────────────────────


def test_broker_visibility_timeout_covers_the_longest_retry(settings):
    """Redis возвращает неподтверждённую задачу в очередь через `visibility_timeout`; отложенный ретрай на
    24 ч обязан жить в брокере дольше этого срока."""
    from core.celery import app

    options = settings.CELERY_BROKER_TRANSPORT_OPTIONS
    assert options["visibility_timeout"] >= max(RETRY_DELAYS) + 3600
    assert app.conf.broker_transport_options["visibility_timeout"] == options["visibility_timeout"]


def test_beat_runs_the_stuck_webhook_sweeper(settings):
    from core.celery import app

    entry = settings.CELERY_BEAT_SCHEDULE["integration-requeue-stuck-webhooks"]
    assert entry["task"] == "integration.requeue_stuck_webhook_events"
    assert entry["schedule"] <= 300  # секунд: зависшее событие подбирается за минуты, не часы
    assert "integration.requeue_stuck_webhook_events" in app.tasks  # worker не отклонит как незарегистрированную


# ─── Подбор зависших PENDING ──────────────────────────────────────────────────


def test_a_never_attempted_pending_event_is_requeued_after_the_grace(mapped_company):
    stuck = _event(mapped_company)
    _created_ago(stuck, minutes=30)
    fresh = _event(mapped_company)  # только что создано: задача доставки ещё могла не дойти до воркера

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        count = requeue_stuck_webhook_events()

    assert count == 1
    delay.assert_called_once_with(stuck.id)
    assert fresh.id not in [call.args[0] for call in delay.call_args_list]


def test_an_event_waiting_for_its_planned_retry_is_left_alone(mapped_company):
    """Ретрай через 6 ч — не «зависшее»: `PENDING` с давней последней попыткой, но будущим `next_attempt_at`."""
    waiting = _event(
        mapped_company,
        attempts=4,
        last_attempt_at=timezone.now() - timedelta(hours=1),
        next_attempt_at=timezone.now() + timedelta(hours=5),
    )
    _created_ago(waiting, hours=2)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        assert requeue_stuck_webhook_events() == 0

    delay.assert_not_called()


def test_a_retry_that_never_ran_is_requeued_after_its_time_plus_the_grace(mapped_company):
    """Задачу на ретрай потеряли (рестарт Redis, истёк visibility): срок прошёл, а попытки нет."""
    lost = _event(
        mapped_company,
        attempts=2,
        last_attempt_at=timezone.now() - timedelta(hours=1),
        next_attempt_at=timezone.now() - STUCK_GRACE - timedelta(minutes=1),
    )

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        assert requeue_stuck_webhook_events() == 1

    delay.assert_called_once_with(lost.id)


@pytest.mark.parametrize("status", [WebhookEventStatus.SENT, WebhookEventStatus.FAILED])
def test_sent_and_failed_events_are_never_requeued_by_the_sweeper(mapped_company, status):
    """FAILED разбирает человек («Повторить»); SENT доставлено."""
    event = _event(mapped_company, status=status)
    _created_ago(event, days=3)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        assert requeue_stuck_webhook_events() == 0

    delay.assert_not_called()


def test_the_sweeper_does_not_pile_up_tasks_while_the_first_one_waits(mapped_company):
    """Воркер лежит: на каждом проходе Beat новая задача не ставится, пока не вышла пауза после прошлой."""
    stuck = _event(mapped_company)
    _created_ago(stuck, minutes=30)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        assert requeue_stuck_webhook_events() == 1
        assert requeue_stuck_webhook_events() == 0

    assert delay.call_count == 1
    stuck.refresh_from_db()
    assert stuck.next_attempt_at > timezone.now()


def test_the_sweeper_takes_a_bounded_batch(mapped_company):
    for _ in range(3):
        event = _event(mapped_company)
        _created_ago(event, hours=1)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        assert requeue_stuck_webhook_events(batch=2) == 2

    assert delay.call_count == 2


# ─── Время следующей попытки ведёт сама доставка ──────────────────────────────


def test_a_failed_attempt_records_when_the_next_one_is_due(mapped_company):
    from celery.exceptions import Retry

    event = _event(mapped_company)
    with patch("httpx.Client.post", return_value=MagicMock(status_code=500, text="boom")):
        with patch.object(deliver_webhook_event, "retry", side_effect=Retry("r")):
            with pytest.raises(Retry):
                deliver_webhook_event(event.id)

    event.refresh_from_db()
    assert event.status == WebhookEventStatus.PENDING
    expected = event.last_attempt_at + timedelta(seconds=RETRY_DELAYS[0])
    assert abs((event.next_attempt_at - expected).total_seconds()) < 5


def test_a_delivered_or_exhausted_event_has_no_next_attempt(mapped_company):
    ok = _event(mapped_company, next_attempt_at=timezone.now())
    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")):
        deliver_webhook_event(ok.id)
    ok.refresh_from_db()
    assert (ok.status, ok.next_attempt_at) == (WebhookEventStatus.SENT, None)

    spent = _event(mapped_company, attempts=len(RETRY_DELAYS), next_attempt_at=timezone.now())
    with patch("httpx.Client.post", return_value=MagicMock(status_code=503, text="down")):
        deliver_webhook_event(spent.id)
    spent.refresh_from_db()
    assert (spent.status, spent.next_attempt_at) == (WebhookEventStatus.FAILED, None)


def test_manual_redelivery_gives_a_failed_event_a_full_retry_cycle(mapped_company):
    """Иначе «Повторить» после исчерпанных попыток делал бы ровно одну и снова FAILED."""
    event = _event(mapped_company, status=WebhookEventStatus.FAILED, attempts=len(RETRY_DELAYS) + 1)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        redeliver_event(event.id)

    event.refresh_from_db()
    assert (event.status, event.attempts) == (WebhookEventStatus.PENDING, 0)
    delay.assert_called_once_with(event.id)


# ─── Не теряется: нет секрета ─────────────────────────────────────────────────


def test_an_event_emitted_without_a_secret_is_kept_pending_not_dropped(mapped_company, settings):
    settings.ERP_WEBHOOK_SECRET = ""

    event = emit_event("invite.sent", mapped_company.id, {"channels": ["email"]}, send_async=False)

    assert event is not None
    assert event.status == WebhookEventStatus.PENDING
    assert IntegrationWebhookEvent.objects.count() == 1


def test_delivery_without_a_secret_waits_and_goes_out_once_the_secret_is_set(mapped_company, settings):
    settings.ERP_WEBHOOK_SECRET = ""
    event = emit_event("invite.sent", mapped_company.id, {"channels": ["email"]}, send_async=False)
    _created_ago(event, minutes=30)

    with patch("httpx.Client.post") as post:
        assert deliver_webhook_event(event.id) is False
        post.assert_not_called()
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.PENDING
    assert event.attempts == 0, "без секрета попытка не засчитывается"

    settings.ERP_WEBHOOK_SECRET = "test-webhook-secret"
    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")) as post:
        with patch("integration.tasks.deliver_webhook_event.delay", side_effect=lambda pk: deliver_webhook_event(pk)):
            assert requeue_stuck_webhook_events() == 1
        post.assert_called_once()
        assert post.call_args.kwargs["headers"]["X-Signature"].startswith("sha256=")
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.SENT


# ─── Журнал доставок в админке ────────────────────────────────────────────────


@pytest.fixture
def root(db):
    return CustomUser.objects.create_user(
        email="root@webhooks.test",
        username="root_webhooks",
        password="Probe1234!",
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


@pytest.fixture
def staff_engineer(db):
    """Инженер без суперправа: журнал смотрит, «Повторить» не видит."""
    from django.contrib.auth.models import Group, Permission

    user = CustomUser.objects.create_user(
        email="eng@webhooks.test",
        username="eng_webhooks",
        password="Probe1234!",
        is_staff=True,
        is_active=True,
    )
    group, _ = Group.objects.get_or_create(name="system_engineers")
    user.groups.add(group)
    user.user_permissions.add(Permission.objects.get(codename="view_integrationwebhookevent"))
    return user


def _changelist() -> str:
    return reverse("admin:integration_integrationwebhookevent_changelist")


def _post_redeliver(client, events, **extra):
    payload = {"action": "redeliver_selected", ACTION_CHECKBOX_NAME: [str(e.pk) for e in events], **extra}
    return client.post(_changelist(), payload, follow=False)


def test_the_delivery_journal_is_in_the_admin_and_shows_status_and_error(client, root, mapped_company):
    failed = _event(mapped_company, status=WebhookEventStatus.FAILED, attempts=7, last_error="HTTP 503: down")
    client.force_login(root)

    page = client.get(_changelist())

    assert page.status_code == 200
    body = page.content.decode()
    assert str(failed.event_id) in body
    assert "invite.sent" in body
    assert client.get(reverse("admin:integration_integrationwebhookevent_change", args=[failed.pk])).status_code == 200


def test_the_journal_is_read_only_even_for_the_superuser(root, mapped_company):
    """Журнал — след доставки, а не форма: ни добавить, ни поправить тело события, ни удалить."""
    event = _event(mapped_company)
    model_admin = admin.site._registry[IntegrationWebhookEvent]
    request = MagicMock(user=root)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_delete_permission(request, event) is False
    assert model_admin.has_change_permission(request, event) is False


def test_redeliver_asks_for_confirmation_and_a_reason_first(client, root, mapped_company):
    event = _event(mapped_company, status=WebhookEventStatus.FAILED)
    client.force_login(root)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        asked = _post_redeliver(client, [event])
        no_reason = _post_redeliver(client, [event], _emergency_confirmed="1", _emergency_reason="  ")

    assert asked.status_code == 200 and no_reason.status_code == 200, "экран подтверждения, не выполнение"
    delay.assert_not_called()
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.FAILED


def test_the_confirmed_redeliver_requeues_the_event(client, root, mapped_company):
    event = _event(mapped_company, status=WebhookEventStatus.FAILED, attempts=7, last_error="HTTP 503: down")
    client.force_login(root)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        _post_redeliver(client, [event], _emergency_confirmed="1", _emergency_reason="CRM вернулась после аварии")

    delay.assert_called_once_with(event.id)
    event.refresh_from_db()
    assert (event.status, event.attempts) == (WebhookEventStatus.PENDING, 0)


def test_redeliver_skips_sent_and_events_waiting_for_their_own_retry(client, root, mapped_company):
    """Иначе «Повторить» по PENDING с запланированным ретраем даёт вторую параллельную цепочку попыток."""
    sent = _event(mapped_company, status=WebhookEventStatus.SENT)
    waiting = _event(
        mapped_company,
        attempts=3,
        next_attempt_at=timezone.now() + timedelta(hours=5),
    )
    stuck = _event(mapped_company, attempts=1, next_attempt_at=timezone.now() - timedelta(hours=1))
    failed = _event(mapped_company, status=WebhookEventStatus.FAILED, attempts=7)
    client.force_login(root)

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        _post_redeliver(client, [sent, waiting, stuck, failed], _emergency_confirmed="1", _emergency_reason="проверка")

    assert sorted(call.args[0] for call in delay.call_args_list) == sorted([stuck.id, failed.id])
    waiting.refresh_from_db()
    assert waiting.attempts == 3, "ждущий своего ретрая не тронут"


def test_redeliver_leaves_a_trace_in_the_access_log(client, root, mapped_company):
    from crm.models import ActivityLog

    event = _event(mapped_company, status=WebhookEventStatus.FAILED)
    client.force_login(root)

    with patch("integration.tasks.deliver_webhook_event.delay"):
        _post_redeliver(client, [event], _emergency_confirmed="1", _emergency_reason="CRM вернулась")

    entry = ActivityLog.objects.get(event_code="admin.emergency.redeliver_selected")
    assert entry.reason == "CRM вернулась"
    assert entry.user_id == root.pk


def test_an_engineer_without_superuser_sees_the_journal_but_not_the_action(client, staff_engineer, mapped_company):
    event = _event(mapped_company, status=WebhookEventStatus.FAILED)
    client.force_login(staff_engineer)

    assert client.get(_changelist()).status_code == 200
    model_admin = admin.site._registry[IntegrationWebhookEvent]
    assert "redeliver_selected" not in model_admin.get_actions(MagicMock(user=staff_engineer))

    with patch("integration.tasks.deliver_webhook_event.delay") as delay:
        _post_redeliver(client, [event], _emergency_confirmed="1", _emergency_reason="пробую")

    delay.assert_not_called()
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.FAILED
