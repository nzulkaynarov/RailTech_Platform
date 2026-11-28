"""ТЕСТ-2: решение шлюза доставки — можно ли создать уведомление этому сотруднику по этой записи."""

import logging

from django.conf import settings

from notifications.subjects import is_deal_scoped

logger = logging.getLogger(__name__)


def sees_tests(user_id: int | None) -> bool:
    """У сотрудника включено «Показывать тестовые» (копия флага CRM в `preferences`)."""
    if user_id is None:
        return False
    from accounts.models import CustomUser

    prefs = CustomUser.objects.filter(pk=user_id).values_list("preferences", flat=True).first()
    return bool(isinstance(prefs, dict) and prefs.get("show_test") is True)


def deal_of_test_company(deal_id: int | None) -> bool:
    if deal_id is None:
        return False
    from crm.models import Deal

    return Deal.objects.filter(pk=deal_id, company__is_test=True).exists()


def may_receive(user_id: int | None, deal_id: int | None) -> bool:
    """Запись рабочая — можно всем; тестовой компании — только сотруднику с включённым показом."""
    return not deal_of_test_company(deal_id) or sees_tests(user_id)


def deliverable(notification) -> bool:
    code = notification.event_code or ""
    if notification.user_id is None:  # служебное уведомление администраторам платформы
        return True
    if notification.deal_id is None and is_deal_scoped(code):
        message = f"уведомление {code!r} о записи сделки создано без deal="
        if getattr(settings, "NOTIFICATION_SUBJECT_STRICT", False):
            raise ValueError(message)
        logger.error("%s — пропущено", message)
        return False
    return may_receive(notification.user_id, notification.deal_id)


def staff_recipients(user_ids, deal) -> list[int]:
    """Кому из сотрудников слать письмо о записи сделки: по тестовой компании — только с включённым показом."""
    ids = list(dict.fromkeys(user_ids))
    if not deal_of_test_company(getattr(deal, "pk", deal)):
        return ids
    return [uid for uid in ids if sees_tests(uid)]
