"""Break-glass (audited emergency access) — ADR-0004 G2.

A Platform Operator does NOT normally see a tenant's private trade data (deals, quotes,
contracts). When support/moderation genuinely needs it, they OPEN a break-glass session:
a reason-required, time-boxed, entity-scoped audit record. This module exposes:

  POST /api/v1/admin/break-glass/  — open a break-glass grant (records BREAK_GLASS)
  GET  /api/v1/admin/access-log/   — the «Журнал доступа»: break-glass + force-override feed

Both are gated by the operator capability `moderation.force_override` (OperatorScoped).
All logic routes through core.audit.log_admin_action so the timeline stays consistent.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import log_admin_action
from core.permissions import OperatorScoped

# Private tenant entities a break-glass grant may cover. Restricting the set keeps the
# audit meaningful and prevents arbitrary entity_type spam.
BREAK_GLASS_ENTITIES = {"deal", "quote", "contract"}
_DEFAULT_MINUTES = 60
_MIN_MINUTES = 5
_MAX_MINUTES = 480  # 8h hard cap — a grant is temporary by definition


def record_break_glass(operator, *, entity_type: str, entity_id: int, reason: str, minutes: int):
    """Write the reason-required, time-boxed BREAK_GLASS audit record (Rule 8: logic here,
    not in the view). Returns the created ActivityLog."""
    expires_at = timezone.now() + timedelta(minutes=minutes)
    return log_admin_action(
        entity_type=entity_type,
        entity_id=entity_id,
        action="BREAK_GLASS открыт доступ оператора",
        detail=f"Оператор {operator.email} открыл временный доступ к {entity_type} #{entity_id} "
        f"до {expires_at:%Y-%m-%d %H:%M} UTC.",
        actor=operator,
        reason=reason,
        level="WARNING",
        expires_at=expires_at,
        # Код нужен по той же причине, что и остальным событиям ленты: без него «Журнал
        # доступа» печатает русскую строку `action` оператору с английским интерфейсом.
        event_code="admin.break_glass.opened",
        event_params={
            "operator_email": operator.email,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    )


@extend_schema(
    summary="Open a break-glass access grant (audited, time-boxed)",
    description="Records a reason-required, entity-scoped BREAK_GLASS log so an operator's "
    "access to a tenant's private deal/quote/contract is attributable and expires.",
    request=inline_serializer(
        "BreakGlassRequest",
        fields={
            "entity_type": serializers.CharField(),
            "entity_id": serializers.IntegerField(),
            "reason": serializers.CharField(),
            "minutes": serializers.IntegerField(required=False),
        },
    ),
    responses={201: OpenApiResponse(description="Break-glass grant recorded")},
    tags=["Admin"],
)
class BreakGlassView(APIView):
    permission_classes = [IsAuthenticated, OperatorScoped]
    operator_permission = "moderation.force_override"

    def post(self, request):
        entity_type = (request.data.get("entity_type") or "").strip().lower()
        reason = (request.data.get("reason") or "").strip()
        entity_id_raw = request.data.get("entity_id")
        if entity_type not in BREAK_GLASS_ENTITIES:
            return Response({"detail": "INVALID_ENTITY_TYPE", "allowed": sorted(BREAK_GLASS_ENTITIES)}, status=400)
        try:
            entity_id = int(entity_id_raw)
        except (TypeError, ValueError):
            return Response({"detail": "INVALID_ENTITY_ID"}, status=400)
        if not reason:
            return Response({"detail": "FORCE_REASON_REQUIRED"}, status=400)
        try:
            minutes = int(request.data.get("minutes", _DEFAULT_MINUTES))
        except (TypeError, ValueError):
            minutes = _DEFAULT_MINUTES
        minutes = max(_MIN_MINUTES, min(minutes, _MAX_MINUTES))

        log = record_break_glass(
            request.user, entity_type=entity_type, entity_id=entity_id, reason=reason, minutes=minutes
        )
        return Response(
            {
                "id": log.id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "reason": reason,
                "expires_at": log.expires_at.isoformat() if log.expires_at else None,
            },
            status=201,
        )


@extend_schema(
    summary="Access log — break-glass + force-override feed",
    description="Platform-wide feed of break-glass grants and force-override actions "
    "(force-approve quote, force-cancel contract, forced deal-stage), newest first. "
    "Powers the admin «Журнал доступа» page.",
    parameters=[
        OpenApiParameter(name="limit", description="Max items (default 100, max 500)", required=False, type=int),
    ],
    responses={200: OpenApiResponse(description="Access-log entries")},
    tags=["Admin"],
)
class AdminAccessLogView(APIView):
    permission_classes = [IsAuthenticated, OperatorScoped]
    operator_permission = "moderation.force_override"

    def get(self, request):
        from django.db.models import Q

        from crm.audit_display import actor_display_name
        from crm.models import ActivityLog

        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        # Что показывает «Журнал доступа»: всё, чем оператор трогает ЧУЖИЕ права и деньги.
        #
        # Раньше лента ограничивалась break-glass (есть `expires_at`) и force-override (маркер
        # `[FORCE_ADMIN]` в тексте). Из-за этого волна аудита 20-08 писала след, которого
        # оператор НЕ ВИДЕЛ: деактивация аккаунта, выдача роли платформенного администратора,
        # отзыв платного права и приостановка подписки в ленту не попадали. Записано ≠ видно —
        # тот же класс, что «показано ≠ работает».
        #
        # Эталон — Salesforce Setup Audit Trail: один список административных изменений (роли,
        # права, деактивации), а не отдельная витрина под аварийный доступ.
        #
        # Отбор идёт по МАШИННОМУ коду `admin.*`, а не по тексту действия: `[FORCE_ADMIN]`
        # ловился подстрокой и ломался бы от любой правки формулировки.
        qs = (
            ActivityLog.objects.select_related("user")
            .filter(
                Q(expires_at__isnull=False) | Q(action__icontains="[FORCE_ADMIN]") | Q(event_code__startswith="admin.")
            )
            .order_by("-timestamp")
        )
        now = timezone.now()
        items = [
            {
                "id": log.id,
                "action": log.action,
                "detail": log.detail,
                "level": log.level,
                "reason": log.reason,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "user_email": log.user.email if log.user else None,
                # Тот же откат, что в ленте сделки и журнале активности: `get_full_name()` пуст
                # у служебных и заведённых оператором аккаунтов, и запись С автором выглядела
                # как запись БЕЗ автора.
                "user_name": actor_display_name(log),
                # Код и параметры нужны фронту, чтобы напечатать событие НА ЯЗЫКЕ СМОТРЯЩЕГО:
                # без них `activityTitle` откатывался на русскую строку `action`, и англоязычный
                # оператор читал русское.
                "event_code": log.event_code,
                "event_params": log.event_params or {},
                "timestamp": log.timestamp.isoformat(),
                "expires_at": log.expires_at.isoformat() if log.expires_at else None,
                "is_break_glass": log.expires_at is not None,
                "is_force_override": "[FORCE_ADMIN]" in (log.action or ""),
                "is_active": bool(log.expires_at and log.expires_at > now),
            }
            for log in qs[:limit]
        ]
        return Response({"count": len(items), "items": items})
