"""L1 — уведомления несут машинный код события (spec-bilingual-ru-en-2026-08-02).

«По проводам коды, слова на краях»: бэкенд пишет `event_code` + `event_params`, текст на
языке ЗРИТЕЛЯ собирает клиент (`frontend/src/lib/notificationText.ts`). `title`/`message`
остаются RU-fallback — для строк, записанных до L1, и для Unfold-админки.
"""

import pytest

from notifications.models import Notification, NotificationType
from notifications.services import notify_platform_admins, notify_user


@pytest.fixture
def info_type(db):
    return NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})[0]


@pytest.fixture
def user(db):
    from accounts.models import CustomUser

    return CustomUser.objects.create_user(email="n@codes.test", username="n@codes.test", password="x")


@pytest.mark.django_db
def test_notify_user_stores_code_and_params(info_type, user):
    notification = notify_user(
        user=user,
        title="Счёт выставлен",
        message="По сделке #7 выставлен счёт INV-1",
        event_code="invoice.issued",
        event_params={"deal_id": 7, "number": "INV-1"},
        push=False,
    )

    assert notification.event_code == "invoice.issued"
    assert notification.event_params == {"deal_id": 7, "number": "INV-1"}
    assert notification.title == "Счёт выставлен", "RU-fallback обязан сохраниться"


@pytest.mark.django_db
def test_notification_without_code_still_works(info_type, user):
    """Broadcast'ы и админские произвольные уведомления кода не несут — и это норма."""
    notification = notify_user(user=user, title="Произвольное", message="Текст", push=False)

    assert notification.event_code == ""
    assert notification.event_params == {}


@pytest.mark.django_db
def test_platform_admin_alert_carries_code(info_type):
    notification = notify_platform_admins(
        title="Запрошена новая категория",
        message="Buyer Co: «Тормозные колодки»",
        type_code="INFO",
        event_code="catalog.category_requested",
        event_params={"request_id": 3, "company_name": "Buyer Co", "category_name": "Тормозные колодки"},
    )

    assert notification.audience == Notification.AUDIENCE_PLATFORM_ADMIN
    assert notification.event_code == "catalog.category_requested"


@pytest.mark.django_db
def test_serializer_exposes_code_and_params(info_type, user):
    from notifications.serializers import NotificationSerializer

    notification = notify_user(
        user=user, title="t", message="m", event_code="act.issued", event_params={"number": "ACT-1"}, push=False
    )
    data = NotificationSerializer(notification).data

    assert data["event_code"] == "act.issued"
    assert data["event_params"] == {"number": "ACT-1"}


@pytest.mark.django_db
def test_deal_producers_emit_codes(db):
    """Ключевые события сделки обязаны нести код — иначе они останутся русскими навсегда."""
    import inspect

    from crm.services import deal_notifications

    source = inspect.getsource(deal_notifications)
    for code in (
        "payment.recorded",
        "act.issued",
        "act.signed",
        "act.rejected",
        "act.cancelled",
        "fulfillment.status_changed",
        "fulfillment.overdue",
    ):
        assert f'event_code="{code}"' in source, f"производитель {code} потерял код"
