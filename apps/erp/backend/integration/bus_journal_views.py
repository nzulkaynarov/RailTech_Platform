"""«Журнал интеграций» шины rt_bus в Admin Платформы (W13-A2): `/api/v1/integration/bus/*`.

То, что раньше было только в `manage.py bus_retry` и Django admin («Delivery/Inbox/SubscriberState»): сводка подписчиков
(очередь, DLQ, предохранитель), доставки с фильтрами, принятые события с ошибками, «Повторить», «Повторить все dead
подписчика», повтор обработки. Логика — библиотечная (`rt_bus`, общая с CRM и EDS); поля ответа — те же, что у CRM и EDS
(BFF сводит три домена в один журнал). Тел событий API не отдаёт — только метаданные доставки.

Право — код раздела `admin` каталога Платформы в ERP: `team.manage` (или администратор ERP — `is_superuser`); это и
чтение, и повтор. Повтор идемпотентен (нечего повторять — `retried: 0`) и пишется в журнал (`admin.bus.*`) с автором.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.constants import Permission
from core.audit import log_admin_action
from core.permissions import ROLE_NOT_PERMITTED, RoleGatedViewMixin

from .bus import get_bus

SUBSCRIBER_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
DELIVERY_STATUSES = ["pending", "in_flight", "delivered", "dead"]
INBOX_STATUSES = ["received", "processed", "failed", "skipped"]
TAGS = ["System"]


class CanManageBus(BasePermission):
    """Администратор ERP или сотрудник своей компании с `team.manage` (раздел `admin` каталога, уровень `full`)."""

    message = ROLE_NOT_PERMITTED

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import is_seller, staff_has_permission

        return is_seller(user) and staff_has_permission(user, Permission.TEAM_MANAGE.value)


# --- схемы ответа (те же поля, что `BusOverview`… в crm.yaml и eds.yaml) ------------------------------------------


class BusSubscriberSerializer(serializers.Serializer):
    name = serializers.CharField()
    configured = serializers.BooleanField()
    enabled = serializers.BooleanField()
    drop = serializers.BooleanField()
    endpoint = serializers.CharField(allow_null=True)
    pending = serializers.IntegerField()
    in_flight = serializers.IntegerField()
    dead = serializers.IntegerField()
    oldest_undelivered_age_seconds = serializers.FloatField(allow_null=True)
    consecutive_failures = serializers.IntegerField()
    paused_until = serializers.DateTimeField(allow_null=True)
    last_failure_at = serializers.DateTimeField(allow_null=True)
    last_success_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_null=True)


class BusOverviewSerializer(serializers.Serializer):
    service = serializers.CharField()
    outbox_pending = serializers.IntegerField()
    oldest_undelivered_age_seconds = serializers.FloatField(allow_null=True)
    dlq_size = serializers.IntegerField()
    inbox_received = serializers.IntegerField()
    inbox_retrying = serializers.IntegerField()
    inbox_failed = serializers.IntegerField()
    subscribers = BusSubscriberSerializer(many=True)


class BusDeliverySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_id = serializers.UUIDField()
    event_type = serializers.CharField()
    subscriber = serializers.CharField()
    status = serializers.ChoiceField(choices=DELIVERY_STATUSES)
    attempts = serializers.IntegerField()
    next_attempt_at = serializers.DateTimeField(allow_null=True)
    last_attempt_at = serializers.DateTimeField(allow_null=True)
    last_status_code = serializers.IntegerField(allow_null=True)
    last_error = serializers.CharField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    subject = serializers.CharField(allow_null=True)
    correlation_id = serializers.CharField(allow_null=True)
    event_created_at = serializers.DateTimeField(allow_null=True)


class BusDeliveryPageSerializer(serializers.Serializer):
    items = BusDeliverySerializer(many=True)
    has_more = serializers.BooleanField()


class BusInboxEntrySerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    type = serializers.CharField()
    publisher = serializers.CharField()
    subject = serializers.CharField(allow_null=True)
    correlation_id = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=INBOX_STATUSES)
    attempts = serializers.IntegerField()
    error = serializers.CharField(allow_null=True)
    received_at = serializers.DateTimeField()
    processed_at = serializers.DateTimeField(allow_null=True)


class BusInboxPageSerializer(serializers.Serializer):
    items = BusInboxEntrySerializer(many=True)
    has_more = serializers.BooleanField()


class BusRetryResultSerializer(serializers.Serializer):
    retried = serializers.IntegerField(min_value=0)


class BusRetryDeadInSerializer(serializers.Serializer):
    subscriber = serializers.RegexField(SUBSCRIBER_PATTERN, max_length=64)


# --- фильтры запроса ----------------------------------------------------------------------------------------------


class _Limit(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=50)


class DeliveriesQuery(_Limit):
    status = serializers.ChoiceField(choices=DELIVERY_STATUSES, required=False)
    subscriber = serializers.RegexField(SUBSCRIBER_PATTERN, max_length=64, required=False)
    type = serializers.CharField(min_length=1, max_length=200, required=False)
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)
    before_id = serializers.IntegerField(min_value=1, required=False)


class InboxQuery(_Limit):
    errors = serializers.BooleanField(required=False, default=False)
    status = serializers.ChoiceField(choices=INBOX_STATUSES, required=False)
    type = serializers.CharField(min_length=1, max_length=200, required=False)
    before = serializers.DateTimeField(required=False)
    before_event_id = serializers.UUIDField(required=False)


def _query(serializer_class, request) -> dict:
    query = serializer_class(data=request.query_params)
    query.is_valid(raise_exception=True)
    return dict(query.validated_data)


def _actor(request) -> str:
    return f"erp-user:{request.user.pk}"


def _audit(request, entity_type: str, entity_id: int, action: str, detail: str, code: str, retried: int) -> None:
    log_admin_action(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        detail=detail,
        actor=request.user,
        event_code=f"admin.bus.{code}",
        event_params={"retried": retried},
        after={"retried": retried},
    )


class _BusView(APIView):
    permission_classes = [IsAuthenticated, CanManageBus]


class _BusWriteView(RoleGatedViewMixin, _BusView):
    required_permissions = {"POST": Permission.TEAM_MANAGE.value}


# --- вьюхи --------------------------------------------------------------------------------------------------------


class BusOverviewView(_BusView):
    """GET /api/v1/integration/bus/overview/ — сводка шины ERP: outbox, DLQ, inbox, подписчики."""

    @extend_schema(
        operation_id="busOverview",
        summary="Журнал шины: сводка и подписчики",
        responses={200: BusOverviewSerializer},
        tags=TAGS,
    )
    def get(self, request):
        return Response(BusOverviewSerializer(asdict(get_bus().overview())).data)


class BusDeliveriesView(_BusView):
    """GET /api/v1/integration/bus/deliveries/ — доставки событий ERP, новые сверху; DLQ — `status=dead`."""

    @extend_schema(
        operation_id="busDeliveries",
        summary="Журнал шины: доставки (DLQ — status=dead)",
        parameters=[DeliveriesQuery],
        responses={200: BusDeliveryPageSerializer},
        tags=TAGS,
    )
    def get(self, request):
        q = _query(DeliveriesQuery, request)
        limit = q["limit"]
        rows = get_bus().list_deliveries(
            status=q.get("status"),
            subscriber=q.get("subscriber"),
            type_contains=q.get("type"),
            created_from=q.get("created_from"),
            created_to=q.get("created_to"),
            before_id=q.get("before_id"),
            limit=limit + 1,
        )
        page = {"items": [asdict(r) for r in rows[:limit]], "has_more": len(rows) > limit}
        return Response(BusDeliveryPageSerializer(page).data)


class BusDeliveryRetryView(_BusWriteView):
    """POST /api/v1/integration/bus/deliveries/{delivery_id}/retry/ — «Повторить» доставку."""

    @extend_schema(
        operation_id="busRetryDelivery",
        summary="Журнал шины: повторить доставку (dead или ожидающую)",
        request=None,
        responses={200: BusRetryResultSerializer},
        tags=TAGS,
    )
    def post(self, request, delivery_id: int):
        done = int(get_bus().retry_delivery(delivery_id, actor=_actor(request)))
        _audit(
            request,
            "bus_delivery",
            delivery_id,
            "Повтор доставки шины",
            f"Доставка {delivery_id}, поставлено: {done}",
            "delivery_retried",
            done,
        )
        return Response({"retried": done})


class BusRetryDeadView(_BusWriteView):
    """POST /api/v1/integration/bus/deliveries/retry-dead/ — «Повторить все dead подписчика»."""

    @extend_schema(
        operation_id="busRetryDead",
        summary="Журнал шины: повторить все dead подписчика",
        request=BusRetryDeadInSerializer,
        responses={200: BusRetryResultSerializer},
        tags=TAGS,
    )
    def post(self, request):
        body = BusRetryDeadInSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        subscriber = body.validated_data["subscriber"]
        count = get_bus().retry_all_dead(subscriber, actor=_actor(request))
        _audit(
            request,
            "bus_subscriber",
            0,
            "Повтор всех dead подписчика шины",
            f"Подписчик {subscriber}, поставлено: {count}",
            "dead_retried",
            count,
        )
        return Response({"retried": count})


class BusInboxView(_BusView):
    """GET /api/v1/integration/bus/inbox/ — принятые события; `errors=true` — обработка упала или ждёт повтора."""

    @extend_schema(
        operation_id="busInbox",
        summary="Журнал шины: принятые события (errors=true — с ошибкой)",
        parameters=[InboxQuery],
        responses={200: BusInboxPageSerializer},
        tags=TAGS,
    )
    def get(self, request):
        q = _query(InboxQuery, request)
        limit = q["limit"]
        rows = get_bus().list_inbox(
            status=q.get("status"),
            type_contains=q.get("type"),
            errors_only=q["errors"],
            before=q.get("before"),
            before_event_id=q.get("before_event_id"),
            limit=limit + 1,
        )
        page = {"items": [asdict(r) for r in rows[:limit]], "has_more": len(rows) > limit}
        return Response(BusInboxPageSerializer(page).data)


class BusInboxRetryView(_BusWriteView):
    """POST /api/v1/integration/bus/inbox/{event_id}/retry/ — повторить обработку записи `failed`/`skipped`."""

    @extend_schema(
        operation_id="busRetryInbox",
        summary="Журнал шины: повторить обработку принятого события",
        request=None,
        responses={200: BusRetryResultSerializer},
        tags=TAGS,
    )
    def post(self, request, event_id: str):
        try:
            key = uuid.UUID(event_id)
        except ValueError as exc:
            raise ValidationError({"event_id": ["Must be a valid UUID."]}) from exc
        done = int(get_bus().retry_inbox(key, actor=_actor(request)))
        _audit(
            request,
            "bus_inbox",
            0,
            "Повтор обработки события шины",
            f"Событие {event_id}, поставлено: {done}",
            "inbox_retried",
            done,
        )
        return Response({"retried": done})
