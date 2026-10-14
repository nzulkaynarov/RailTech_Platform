from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts import services
from accounts.models import CompanyEntitlement, SupplierSubscription
from accounts.serializers import CompanyEntitlementSerializer, SupplierSubscriptionSerializer
from core.audit import AuditedWriteMixin
from core.permissions import IsPlatformAdmin


@extend_schema_view(
    list=extend_schema(
        summary="List subscriptions",
        description="Returns all supplier subscriptions. Filterable by plan, status, company.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create subscription", description="Create a new supplier subscription.", tags=["Accounts"]
    ),
    retrieve=extend_schema(summary="Get subscription details", tags=["Accounts"]),
    update=extend_schema(summary="Update subscription", tags=["Accounts"]),
    partial_update=extend_schema(summary="Partially update subscription", tags=["Accounts"]),
    destroy=extend_schema(summary="Delete subscription", tags=["Accounts"]),
)
class SupplierSubscriptionViewSet(AuditedWriteMixin, viewsets.ModelViewSet):
    """
    CRUD + status actions for supplier subscriptions.
    Admin/Manager only.
    """

    serializer_class = SupplierSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    # Operator sub-capability per action (ADR-0004 G1). `mine`/`pay` are member-facing
    # (own IsAuthenticated permission_classes) so they bypass this map.
    filterset_fields = ["plan", "status", "company"]
    search_fields = ["company__name", "company__inn"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return SupplierSubscription.objects.select_related("company", "currency").order_by("-created_at")

    #: Статус подписки меняют ДЕЙСТВИЯ (`activate`/`suspend`/`bulk-set-status`), а не правка поля.
    #: Через них проходят проверка просроченности, причина, письмо арендатору и запись в журнал —
    #: обычный PATCH не делает ничего из этого (замер 26-08: тот же результат достигался правкой
    #: карточки, и отключённый продавец не получал ни письма, ни причины).
    #: Эталон — Stripe: подписку не «редактируют в статус», её приостанавливают операцией.
    _STATUS_FIELD = "status"

    def update(self, request, *args, **kwargs):
        if self._STATUS_FIELD in request.data:
            current = self.get_object().status
            if str(request.data[self._STATUS_FIELD]) != current:
                return Response(
                    {"detail": "SUBSCRIPTION_STATUS_IS_AN_ACTION"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return super().update(request, *args, **kwargs)

    #: DELETE физически уносил запись вместе с историей оплат и сроком, и в журнале не
    #: оставалось ни того, что удалили, ни кем. CREATE — тем более: подписка это доступ к
    #: платным функциям, и её появление у арендатора обязано быть объяснимо.
    audit_event_prefix = "subscription"

    def audit_entity_type(self, instance) -> str:
        # Короткое `subscription`, а не метка модели: так записаны уже существующие строки
        # журнала, и смена значения оторвала бы новые от старых при разборе инцидента.
        return "subscription"

    def audit_action(self, instance, event: str) -> str:
        return f"Подписка {event}"

    def audit_snapshot(self, instance) -> dict:
        return {
            "plan": instance.plan,
            "status": instance.status,
            "valid_until": str(instance.valid_until) if instance.valid_until else None,
            "monthly_rate": str(instance.monthly_rate) if instance.monthly_rate is not None else None,
        }

    def audit_event_params(self, instance) -> dict:
        return {"company_name": instance.company.name if instance.company_id else str(instance.pk)}

    @extend_schema(
        summary="My subscription",
        description=(
            "Returns the SupplierSubscription of the caller's primary company, "
            "if any. Available to any authenticated user with can_sell capability "
            "on a SUPPLIER/MANUFACTURER company. Platform admin viewers see 204."
        ),
        responses={
            200: SupplierSubscriptionSerializer,
            204: OpenApiResponse(description="No subscription for this user's company"),
            403: OpenApiResponse(description="Platform admin viewer cannot own a subscription"),
        },
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="mine",
        permission_classes=[permissions.IsAuthenticated],
    )
    def mine(self, request):
        """GET /api/v1/accounts/subscriptions/mine/ -- subscription of the current user's company."""
        user = request.user
        if getattr(user, "is_superuser", False):
            return Response(status=status.HTTP_403_FORBIDDEN)
        company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        if not company_ids:
            return Response(status=status.HTTP_204_NO_CONTENT)
        sub = (
            SupplierSubscription.objects.select_related("company", "currency")
            .filter(company_id__in=company_ids)
            .order_by("-updated_at")
            .first()
        )
        if not sub:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Activate subscription",
        description="Set subscription status to ACTIVE.",
        responses={200: SupplierSubscriptionSerializer},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/activate/

        Просроченную подписку одной сменой статуса не активируют: доступ считается по статусу
        И дате сразу, поэтому такая «активация» рисовала ACTIVE, не возвращая ни одной платной
        функции, а ночная задача через сутки откатывала статус. Возобновление — это новый
        период (оплата), как у Stripe и Odoo.
        """
        sub = self.get_object()
        queryset = SupplierSubscription.objects.filter(pk=sub.pk)
        if services.expired_subscription_ids(queryset):
            return Response({"detail": "SUBSCRIPTION_EXPIRED_EXTEND_FIRST"}, status=status.HTTP_400_BAD_REQUEST)
        services.change_subscription_status(queryset, "ACTIVE")
        sub.refresh_from_db()
        self._log_status_change(request, sub, "ACTIVE")
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Suspend subscription",
        description="Set subscription status to SUSPENDED.",
        responses={200: SupplierSubscriptionSerializer},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/suspend/

        Через сервис (Rule 8): приостановка обязана дойти до арендатора письмом и
        уведомлением, а причина — попасть туда, где он её увидит. Голая смена статуса
        отрезала платящего продавца молча.
        """
        sub, error = services.suspend_subscription(
            self.get_object(), actor=request.user, reason=request.data.get("reason", "")
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        self._log_status_change(request, sub, "SUSPENDED")
        return Response(self.get_serializer(sub).data)

    def _log_status_change(self, request, sub, target: str) -> None:
        """След для ОДИНОЧНОЙ смены статуса подписки.

        Массовый вариант (`bulk-set-status`) писал аудит и требовал причину, а одиночная
        кнопка на той же странице не оставляла ничего — приостановка платящего продавца
        отрезала его от отправки КП, и в журнале доступа этого не было видно.

        Причину принимаем, но НЕ требуем: массовая операция затрагивает многих и там барьер
        осмыслен, а вводить его для одиночной — это новая блокировка, которых владелец
        просил не добавлять (PRODUCT RULE 2). Аудит — не гейт.
        """
        from core.audit import log_admin_action

        log_admin_action(
            entity_type="subscription",
            entity_id=sub.pk,
            action=f"Статус подписки → {target}",
            detail=sub.company.name if sub.company_id else str(sub.pk),
            actor=request.user,
            reason=(request.data.get("reason") or "").strip(),
            after={"status": target},
            company_id=sub.company_id,
            level="WARNING" if target == "SUSPENDED" else "SUCCESS",
            event_code="admin.subscription.suspended" if target == "SUSPENDED" else "admin.subscription.activated",
            event_params={"company_name": sub.company.name if sub.company_id else str(sub.pk)},
        )

    @extend_schema(
        summary="Export subscriptions",
        description="Export filtered subscriptions as CSV or XLSX.",
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="subscriptions",
            columns=[
                ("id", "ID", lambda s: s.id),
                ("company", "Company", lambda s: s.company.name if s.company_id else ""),
                ("inn", "INN", lambda s: s.company.inn if s.company_id else ""),
                ("plan", "Plan", lambda s: s.plan),
                ("status", "Status", lambda s: s.status),
                ("monthly_rate", "Monthly rate", lambda s: s.monthly_rate),
                ("currency", "Currency", lambda s: s.currency.code if s.currency_id else ""),
                ("valid_from", "Valid from", lambda s: s.valid_from.isoformat() if s.valid_from else ""),
                ("valid_until", "Valid until", lambda s: s.valid_until.isoformat() if s.valid_until else ""),
            ],
        )

    @extend_schema(
        summary="Bulk set subscription status",
        description="Platform Admin: apply a target status (ACTIVE | SUSPENDED) to multiple subscriptions.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "status": {"type": "string", "enum": ["ACTIVE", "SUSPENDED"]},
                    "reason": {"type": "string"},
                },
                "required": ["ids", "status"],
            }
        },
        responses={200: OpenApiResponse(description="affected count")},
        tags=["Accounts"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-set-status")
    def bulk_set_status(self, request):
        ids = request.data.get("ids") or []
        target = (request.data.get("status") or "").upper()
        reason = (request.data.get("reason") or "").strip()
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "ids (non-empty list) is required"}, status=status.HTTP_400_BAD_REQUEST)
        if target not in ("ACTIVE", "SUSPENDED"):
            return Response({"detail": "status must be one of ACTIVE, SUSPENDED"}, status=status.HTTP_400_BAD_REQUEST)
        if target == "SUSPENDED" and not reason:
            return Response({"detail": "REASON_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        subs = SupplierSubscription.objects.filter(id__in=ids).select_related("company")
        # Массовый путь — тот же, что одиночный: просроченные подписки в ACTIVE не переводим,
        # иначе оператор «активирует» пачку, а доступ не вернётся ни у кого.
        skipped_expired = services.expired_subscription_ids(subs) if target == "ACTIVE" else []
        if skipped_expired:
            subs = subs.exclude(id__in=skipped_expired)
        if target == "SUSPENDED":
            # Массовый путь оповещает так же, как одиночный: молчаливое отключение пачки
            # продавцов — тот же дефект, только шире.
            affected_rows = 0
            for subscription in list(subs):
                _, suspend_error = services.suspend_subscription(subscription, actor=request.user, reason=reason)
                if suspend_error is None:
                    affected_rows += 1
        else:
            affected_rows = services.change_subscription_status(subs, target)
        from core.audit import log_admin_action

        for sub in subs:
            log_admin_action(
                entity_type="subscription",
                entity_id=sub.id,
                action=f"Bulk: статус подписки → {target}",
                detail=f"{sub.company.name} · {target}" if sub.company_id else str(sub.id),
                actor=request.user,
                reason=reason,
                after={"status": target},
                company_id=sub.company_id,
                level="WARNING" if target == "SUSPENDED" else "SUCCESS",
                # Без `event_code` запись НЕ ПОПАДАЛА в «Журнал доступа»: он отбирает ленту по
                # машинному коду `admin.*`. Одиночная кнопка на
                # той же странице код писала, массовая — нет, и отключение ПАЧКИ продавцов было
                # видно хуже, чем отключение одного.
                event_code="admin.subscription.suspended" if target == "SUSPENDED" else "admin.subscription.activated",
                event_params={"company_name": sub.company.name if sub.company_id else str(sub.id)},
            )
        return Response({"affected": affected_rows, "target": target, "skipped_expired": skipped_expired})

    @extend_schema(summary="Record subscription payment -- extends validity and activates", tags=["Accounts"])
    @action(detail=True, methods=["post"], url_path="pay", permission_classes=[permissions.IsAuthenticated])
    def pay(self, request, pk=None):
        sub = self.get_object()
        # `int(...)` на сыром вводе падал в 500 с HTML-страницей вместо `{"detail": "<CODE>"}` —
        # разбор входа делает сервис, вью только передаёт как есть (ARCH-05).
        sub, error = services.record_subscription_payment(
            sub,
            request.data.get("amount", 0),
            months=request.data.get("months", 1),
            actor=request.user,
            manual=True,
        )
        if error:
            # Отказ по ПРАВУ — 403, отказ по ВВОДУ — 400: иначе витрина не отличит «нельзя
            # вам» от «поправьте число».
            http_status = (
                status.HTTP_400_BAD_REQUEST
                if error in ("INVALID_MONTHS", "INVALID_AMOUNT")
                else status.HTTP_403_FORBIDDEN
            )
            return Response({"detail": error}, status=http_status)
        return Response(self.get_serializer(sub).data)


@extend_schema_view(
    list=extend_schema(summary="List company entitlements", tags=["Accounts"]),
    create=extend_schema(summary="Grant a company entitlement", tags=["Accounts"]),
    retrieve=extend_schema(summary="Get entitlement", tags=["Accounts"]),
    update=extend_schema(summary="Update entitlement", tags=["Accounts"]),
    partial_update=extend_schema(summary="Patch entitlement", tags=["Accounts"]),
    destroy=extend_schema(summary="Revoke (delete) entitlement", tags=["Accounts"]),
)
class CompanyEntitlementViewSet(viewsets.ModelViewSet):
    """Platform-admin CRUD of feature entitlements — the monetization control plane (ADR-0006 §3).

    Lets an operator grant a promo, put a company in DEMO, or DISABLE a feature; the app gates on
    `has_entitlement(company, FeatureKey)`. Gated by the billing operator capability (G1).
    """

    serializer_class = CompanyEntitlementSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    filterset_fields = ["company", "feature_key", "access"]
    search_fields = ["company__name", "company__inn", "feature_key"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        return CompanyEntitlement.objects.select_related("company").order_by("-updated_at")

    # Права-энтайтлменты — рычаг монетизации (ADR-0006 §3): строка здесь включает или гасит
    # платную возможность у конкретной компании и ПЕРЕБИВАЕТ подписку. До 20-08 весь этот
    # CRUD был безымянным: в журнале доступа не оставалось ни строки о том, кто выдал промо
    # или посадил компанию в DEMO с водяным знаком на PDF. Пишем след на все три операции —
    # это не гейт, порядок работы оператора не меняется.
    def _log(self, entitlement, action: str, event_code: str, before=None, after=None, level: str = "INFO") -> None:
        from core.audit import log_admin_action

        log_admin_action(
            entity_type="entitlement",
            entity_id=entitlement.pk,
            action=action,
            detail=f"{entitlement.company.name if entitlement.company_id else '—'} · {entitlement.feature_key}",
            actor=self.request.user,
            reason=(self.request.data.get("note") or "").strip(),
            before=before,
            after=after,
            company_id=entitlement.company_id,
            level=level,
            event_code=event_code,
            event_params={
                "company_name": entitlement.company.name if entitlement.company_id else "",
                "feature_key": entitlement.feature_key,
            },
        )

    def perform_create(self, serializer):
        entitlement = serializer.save()
        self._log(
            entitlement,
            "Право выдано",
            "admin.entitlement.granted",
            after={"feature_key": entitlement.feature_key, "access": entitlement.access},
            level="SUCCESS",
        )

    def perform_update(self, serializer):
        before = {"access": serializer.instance.access, "credits": str(serializer.instance.credits)}
        entitlement = serializer.save()
        self._log(
            entitlement,
            "Право изменено",
            "admin.entitlement.changed",
            before=before,
            after={"access": entitlement.access, "credits": str(entitlement.credits)},
        )

    def perform_destroy(self, instance):
        # Пишем ДО удаления: после него ни `pk`, ни компании уже не спросишь.
        self._log(
            instance,
            "Право отозвано",
            "admin.entitlement.revoked",
            before={"feature_key": instance.feature_key, "access": instance.access},
            level="WARNING",
        )
        instance.delete()

    @extend_schema(summary="Feature-key + access-state option lists for the entitlement form", tags=["Accounts"])
    @action(detail=False, methods=["get"], url_path="choices")
    def choices(self, request):
        """Backend-driven option lists for the admin form — the FE never hard-codes the FeatureKey
        or access enums; adding a feature key here surfaces it in the UI with no frontend change."""
        from accounts.constants import FeatureKey

        return Response(
            {
                "feature_keys": [{"value": value, "label": str(label)} for value, label in FeatureKey.choices],
                "access_states": [
                    {"value": value, "label": str(label)} for value, label in CompanyEntitlement.ACCESS_CHOICES
                ],
            }
        )
