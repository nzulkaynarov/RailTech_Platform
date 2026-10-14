"""Сервисы уведомлений — реальным исполнением, а не через мок.

Мотив (приём из волны #457–#460): непокрытая функция — сигнал не «лень написать тест», а
«возможно, она вообще не работает». `notify_platform_admins` до сих пор существовала в тестах
только в виде мока — её тело не выполнялось ни разу. Здесь оно выполняется по-настоящему,
вместе с границей видимости broadcast-канала: платформенный алёрт не должен попадать
обычному пользователю, а клиентское уведомление — оператору.

Плюс закрыты предохранители, которые по определению срабатывают редко: доставка по WebSocket
не имеет права уронить бизнес-операцию, ради которой её позвали.
"""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from notifications.models import Notification, NotificationType
from notifications.services import (
    mark_notifications_read,
    notify_platform_admins,
    notify_user,
    push_notification_ws,
    spa_link,
)

NOTIFICATIONS_URL = "/api/v1/notifications/"


@pytest.fixture
def lookups(db):
    for code in ("INFO", "SUCCESS", "WARNING", "ERROR"):
        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})


@pytest.fixture
def people(lookups):
    """Обычный пользователь компании и платформенный оператор (без членств — ADR-0003)."""
    company = Company.objects.create(name="Notify Co", inn="N100")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    member = CustomUser.objects.create_user(email="member@svc.test", username="member@svc.test", password="x")
    CompanyMember.objects.create(
        user=member,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )
    operator = CustomUser.objects.create_user(
        is_superuser=True,
        email="operator@svc.test",
        username="operator@svc.test",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
    )
    return {"member": member, "operator": operator}


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


# ── notify_platform_admins: тело функции, а не мок ───────────────────────────


def test_notify_platform_admins_creates_a_broadcast_row(people):
    notification = notify_platform_admins("Очередь импорта растёт", "12 файлов ждут обработки")

    assert notification.pk is not None
    assert notification.audience == Notification.AUDIENCE_PLATFORM_ADMIN
    assert notification.user_id is None, "платформенный алёрт адресуется каналу, а не человеку"
    assert notification.type.code == "WARNING", "тип по умолчанию — предупреждение"


def test_platform_alert_reaches_operators_and_not_regular_users(people):
    """Смысл канала: обычный пользователь не должен читать операционные алёрты платформы."""
    alert = notify_platform_admins("Celery завис", "Очередь imports не разбирается 30 минут")

    assert alert.id in _ids(_api(people["operator"]).get(NOTIFICATIONS_URL))
    assert alert.id not in _ids(
        _api(people["member"]).get(NOTIFICATIONS_URL)
    ), "платформенный алёрт утёк обычному пользователю"


def test_user_notification_is_not_shown_to_a_platform_operator(people):
    """Обратная сторона той же границы — оператор не читает клиентские уведомления."""
    personal = notify_user(user=people["member"], title="Инвойс выставлен", message="INV-1", push=False)

    assert personal.id in _ids(_api(people["member"]).get(NOTIFICATIONS_URL))
    assert personal.id not in _ids(_api(people["operator"]).get(NOTIFICATIONS_URL))


# ── notify_user ──────────────────────────────────────────────────────────────


def test_notify_user_without_recipient_returns_none(people):
    """Вызывающему удобнее получить None, чем городить проверку на каждой площадке: у сделок
    сплошь и рядом пустой legacy-получатель."""
    assert notify_user(user=None, title="x", message="y") is None
    assert Notification.objects.filter(title="x").count() == 0


def test_notify_user_pushes_over_websocket_by_default(people):
    with patch("notifications.services.push_notification_ws") as push:
        notification = notify_user(user=people["member"], title="Оплата получена", message="112")
    push.assert_called_once_with(notification)


def test_notify_user_can_skip_the_push(people):
    with patch("notifications.services.push_notification_ws") as push:
        notify_user(user=people["member"], title="Тихое", message="без пуша", push=False)
    push.assert_not_called()


# ── mark_notifications_read ──────────────────────────────────────────────────


def test_mark_notifications_read_counts_only_previously_unread(people):
    unread = notify_user(user=people["member"], title="Первое", message="a", push=False)
    already_read = notify_user(user=people["member"], title="Второе", message="b", push=False)
    Notification.objects.filter(pk=already_read.pk).update(is_read=True)

    updated = mark_notifications_read(Notification.objects.filter(user=people["member"]))

    assert updated == 1, "уже прочитанное не должно попадать в счётчик"
    unread.refresh_from_db()
    assert unread.is_read is True


# ── push_notification_ws: предохранители ─────────────────────────────────────


def test_push_is_skipped_for_a_broadcast_without_a_user(people):
    """У broadcast нет персональной группы — пуш просто не выполняется."""
    alert = notify_platform_admins("Алёрт", "текст")
    with patch("notifications.services.get_channel_layer") as layer:
        push_notification_ws(alert)
    layer.assert_not_called()


def test_push_failure_never_breaks_the_caller(people):
    """Доставка по WebSocket — best-effort: упавший канал не имеет права уронить операцию,
    ради которой уведомление создавалось (оплату, подпись акта)."""
    notification = notify_user(user=people["member"], title="Событие", message="текст", push=False)

    with patch("notifications.services.get_channel_layer", side_effect=RuntimeError("channel layer down")):
        push_notification_ws(notification)  # не должен выбросить исключение

    notification.refresh_from_db()
    assert notification.pk is not None, "запись уведомления должна пережить сбой доставки"


def test_push_payload_carries_the_deal_for_deep_linking(people):
    """Без `deal` живое уведомление приходило «безадресным» и уводило в общий список —
    правильная ссылка появлялась только после перезагрузки страницы."""
    notification = notify_user(
        user=people["member"], title="Оплата получена", message="112", link="#invoices?open=5", push=False
    )

    with patch("notifications.services.async_to_sync") as async_to_sync_mock:
        push_notification_ws(notification)

    sent_payload = async_to_sync_mock.return_value.call_args[0][1]["data"]
    assert "deal" in sent_payload, "в WS-пуше нет поля deal"
    assert sent_payload["link"] == "#invoices?open=5"


# ── spa_link ─────────────────────────────────────────────────────────────────


def test_spa_link_shapes():
    assert spa_link("invoices", 12) == "#invoices?open=12"
    assert spa_link("fulfillments") == "#fulfillments"
