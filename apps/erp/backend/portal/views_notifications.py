"""Колокольчик кабинета (NOTIFY-2, ADR-0023 п. 2): `GET /notifications`, `POST /notifications/read` по `erp-portal.yaml`.

Модуль `profile` — он есть у любой сессии кабинета и не выключается (уведомления — часть профиля контакта, их настройки —
Профиль → «Уведомления»). Контакт и компания — только из сессии; в ленте и в счётчике — только уведомления, чей объект
открыт модулям сессии. Логика — `portal/services/notices.py`.
"""

from portal.exceptions import PortalValidationError
from portal.permissions import HasPortalModule, IsPortalAuthenticated
from portal.services import notices
from portal.views import BasePortalView
from rest_framework import serializers
from rest_framework.response import Response

#: Модуль колокольчика: обязательный у любой сессии (`roles.ALWAYS_ON`).
MODULE = "profile"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class NotificationObjectSerializer(serializers.Serializer):
    type = serializers.CharField(source="object_type")
    id = serializers.IntegerField(source="object_id")
    number = serializers.SerializerMethodField()

    def get_number(self, notice):
        return notice.object_number or None


class PortalNotificationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    group = serializers.CharField()
    object = NotificationObjectSerializer(source="*")
    action = serializers.CharField()
    text_key = serializers.CharField()
    params = serializers.DictField(child=serializers.CharField(allow_blank=True))
    link = serializers.CharField()
    created_at = serializers.DateTimeField()
    read_at = serializers.DateTimeField(allow_null=True)


class NotificationReadMarkSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100, required=False
    )
    all = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("VALIDATION_ERROR")
        # Ровно одно из двух: список или «прочитать все»
        if ("ids" in attrs) == bool(attrs.get("all")):
            raise serializers.ValidationError("VALIDATION_ERROR")
        if "all" in attrs and not attrs["all"]:
            raise serializers.ValidationError("VALIDATION_ERROR")
        return attrs


def _int_param(request, name: str, default, low: int, high: int):
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise PortalValidationError("VALIDATION_ERROR") from None
    if not low <= value <= high:
        raise PortalValidationError("VALIDATION_ERROR")
    return value


class NotificationListView(BasePortalView):
    """GET /notifications — лента контакта по убыванию `id`."""

    required_module = MODULE

    def get(self, request):
        before_id = _int_param(request, "before_id", None, 1, 2**63 - 1)
        limit = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        items, has_more = notices.page(
            request.portal_contact,
            request.portal_company,
            request.portal_modules,
            before_id=before_id,
            limit=limit,
        )
        return Response({"items": PortalNotificationSerializer(items, many=True).data, "has_more": has_more})


class NotificationReadView(BasePortalView):
    """POST /notifications/read — прочитать свои уведомления (`ids`) или все (`all`). Чтение: `can_act` не нужен."""

    required_module = MODULE

    # Отметка «прочитано» — не действие за компанию: право действовать (`CanAct`) не требуется.
    permission_classes = [IsPortalAuthenticated, HasPortalModule]

    def post(self, request):
        serializer = NotificationReadMarkSerializer(data=request.data if isinstance(request.data, dict) else {"_": 1})
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        unread = notices.mark_read(
            request.portal_contact,
            request.portal_company,
            request.portal_modules,
            ids=data.get("ids"),
            all=bool(data.get("all")),
        )
        return Response({"unread": unread})


DEFAULT_NOTIFICATION_SETTINGS = {
    "documents": {"in_app": True, "email": True, "telegram": True, "required": False},
    "money": {"in_app": True, "email": True, "telegram": True, "required": False},
    "deliveries": {"in_app": True, "email": True, "telegram": True, "required": False},
    "messages": {"in_app": True, "email": True, "telegram": True, "required": False},
    "partner_products": {"in_app": True, "email": True, "telegram": True, "required": False},
    "security": {"in_app": True, "email": True, "telegram": True, "required": True},
}


def get_contact_notification_settings(contact) -> dict:
    stored = contact.notification_settings or {}
    result = {}
    for group, defaults in DEFAULT_NOTIFICATION_SETTINGS.items():
        if group == "security":
            result["security"] = {"in_app": True, "email": True, "telegram": True, "required": True}
            continue
        group_stored = stored.get(group, {})
        result[group] = {
            "in_app": True,
            "email": bool(group_stored.get("email", defaults["email"])),
            "telegram": bool(group_stored.get("telegram", defaults["telegram"])),
            "required": False,
        }
    return result


class NotificationChannelUpdateSerializer(serializers.Serializer):
    email = serializers.BooleanField(required=False)
    telegram = serializers.BooleanField(required=False)


class NotificationSettingsUpdateSerializer(serializers.Serializer):
    groups = serializers.DictField(child=NotificationChannelUpdateSerializer(), required=True)

    def validate_groups(self, groups):
        valid_groups = {"documents", "money", "deliveries", "messages", "partner_products"}
        for k in groups.keys():
            if k not in valid_groups:
                raise serializers.ValidationError("VALIDATION_ERROR")
        return groups


class NotificationSettingsView(BasePortalView):
    """GET/PATCH /notifications/settings — Настройки каналов уведомлений контакта (J3, ADR-0023)."""

    required_module = MODULE
    permission_classes = [IsPortalAuthenticated, HasPortalModule]

    def get(self, request):
        contact = request.portal_contact
        return Response(
            {
                "telegram_connected": bool(contact.telegram_user_id),
                "groups": get_contact_notification_settings(contact),
            }
        )

    def patch(self, request):
        serializer = NotificationSettingsUpdateSerializer(data=request.data if isinstance(request.data, dict) else {})
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        contact = request.portal_contact
        updates = serializer.validated_data["groups"]
        stored = dict(contact.notification_settings or {})

        for group, channel_updates in updates.items():
            if group == "security":
                continue
            group_data = dict(stored.get(group, {}))
            if "email" in channel_updates:
                group_data["email"] = channel_updates["email"]
            if "telegram" in channel_updates:
                group_data["telegram"] = channel_updates["telegram"]
            stored[group] = group_data

        contact.notification_settings = stored
        contact.save(update_fields=["notification_settings"])

        return Response(
            {
                "telegram_connected": bool(contact.telegram_user_id),
                "groups": get_contact_notification_settings(contact),
            }
        )
