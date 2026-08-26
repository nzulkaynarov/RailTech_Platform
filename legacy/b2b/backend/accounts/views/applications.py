from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import permissions
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts import services
from accounts.models import Company, CompanyEntitlement, CompanyRoleApplication, SupplierSubscription
from accounts.serializers import (
    CompanyEntitlementSerializer,
    CompanyRoleApplicationSerializer,
    SupplierSubscriptionSerializer,
)
from accounts.services import member_has_permission
from core.permissions import OperatorScoped


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
class SupplierSubscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD + status actions for supplier subscriptions.
    Admin/Manager only.
    """

    serializer_class = SupplierSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    # Operator sub-capability per action (ADR-0004 G1). `mine`/`pay` are member-facing
    # (own IsAuthenticated permission_classes) so they bypass this map.
    operator_permissions = {
        "list": "billing.view",
        "retrieve": "billing.view",
        "export": "billing.view",
        "create": "billing.manage",
        "update": "billing.manage",
        "partial_update": "billing.manage",
        "destroy": "billing.manage",
        "activate": "billing.manage",
        "suspend": "billing.manage",
        "bulk_set_status": "billing.manage",
    }
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

    def perform_create(self, serializer):
        subscription = serializer.save()
        self._log_lifecycle(subscription, "created", after=self._snapshot(subscription))

    def perform_update(self, serializer):
        before = self._snapshot(serializer.instance)
        subscription = serializer.save()
        self._log_lifecycle(subscription, "updated", before=before, after=self._snapshot(subscription))

    def perform_destroy(self, instance):
        # След пишем ДО удаления: после него ни pk, ни компании уже не спросишь. Тот же приём,
        # что у прав компании (`CompanyEntitlementViewSet.perform_destroy`) — механика одна.
        self._log_lifecycle(instance, "deleted", before=self._snapshot(instance))
        instance.delete()

    @staticmethod
    def _snapshot(subscription) -> dict:
        return {
            "plan": subscription.plan,
            "status": subscription.status,
            "valid_until": str(subscription.valid_until) if subscription.valid_until else None,
            "monthly_rate": str(subscription.monthly_rate) if subscription.monthly_rate is not None else None,
        }

    def _log_lifecycle(self, subscription, event: str, before=None, after=None) -> None:
        """След жизненного цикла подписки в «Журнале доступа».

        DELETE физически уносил запись вместе с историей оплат и сроком, и в журнале не
        оставалось ни того, что было удалено, ни кем. CREATE — тем более: подписка это доступ
        к платным функциям, и её появление у арендатора обязано быть объяснимо.
        """
        from core.audit import log_admin_action

        company_name = subscription.company.name if subscription.company_id else str(subscription.pk)
        log_admin_action(
            entity_type="subscription",
            entity_id=subscription.pk,
            action=f"Подписка {event}",
            detail=company_name,
            actor=self.request.user,
            reason=(self.request.data.get("reason") or "").strip(),
            before=before,
            after=after,
            company_id=subscription.company_id,
            level="WARNING" if event == "deleted" else "INFO",
            event_code=f"admin.subscription.{event}",
            event_params={"company_name": company_name},
        )

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
        if getattr(user, "is_platform_admin", False):
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
                # машинному коду `admin.*` (`core/admin_api/break_glass.py`). Одиночная кнопка на
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
    list=extend_schema(
        summary="List role applications",
        description="Returns all company role applications. Filterable by status, type, company.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create role application", description="Submit a new role application for a company.", tags=["Accounts"]
    ),
    retrieve=extend_schema(summary="Get role application details", tags=["Accounts"]),
    update=extend_schema(summary="Update role application", tags=["Accounts"]),
    partial_update=extend_schema(summary="Partially update role application", tags=["Accounts"]),
    destroy=extend_schema(summary="Delete role application", tags=["Accounts"]),
)
class CompanyRoleApplicationViewSet(viewsets.ModelViewSet):
    """
    Company role applications:
      - Admin: full CRUD + approve/reject across all companies.
      - Company OWNER: may list/create/update only their own company's applications.
    """

    serializer_class = CompanyRoleApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    # JSON здесь обязателен: multipart нужен только подаче заявки (там прикладывают договор и
    # NDA), а модерация шлёт обычный JSON `{"reason": "..."}`. Пока в списке были только
    # multipart-парсеры, DRF отвечал на отказ 415 Unsupported Media Type — кнопка «Отклонить» в
    # операторской панели не работала вовсе.
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["status", "requested_type", "company"]
    search_fields = ["company__name", "company__inn"]
    ordering = ["-created_at"]

    _OWNER_ALLOWED_ACTIONS = {"list", "retrieve", "create", "partial_update", "update"}
    _ADMIN_ONLY_ACTIONS = {"approve", "reject", "destroy"}
    # Operator sub-capability per action (ADR-0004 G1).
    #
    # `list`/`retrieve` тоже здесь, и это не формальность: выборка оператора платформы не
    # скоупится ничем (`get_queryset` отдаёт ему ВЕСЬ реестр), поэтому любая суб-роль — включая
    # «Поддержку» с пустым набором прав — читала заявки чужих компаний: название, ИНН, e-mail
    # заявителя и приложенные договор с NDA (замер 26-08). Право на чтение чужих документов —
    # такое же право, как право их одобрять.
    operator_permissions = {
        "list": "moderation.role_applications",
        "retrieve": "moderation.role_applications",
        "approve": "moderation.role_applications",
        "reject": "moderation.role_applications",
        "destroy": "moderation.role_applications",
    }

    def get_permissions(self):
        if self.action in self._ADMIN_ONLY_ACTIONS:
            return [permissions.IsAuthenticated(), OperatorScoped()]
        # Чтение реестра арендатором остаётся открытым — его выборку сужает `get_queryset`.
        # Гейт нужен ровно тем, кому выборка НЕ сужается, то есть оператору платформы.
        if self.action in {"list", "retrieve"} and getattr(self.request.user, "is_platform_admin", False):
            return [permissions.IsAuthenticated(), OperatorScoped()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompanyRoleApplication.objects.none()
        qs = CompanyRoleApplication.objects.select_related(
            "company", "requested_type", "submitted_by", "reviewed_by"
        ).order_by("-created_at")
        user = self.request.user
        if user.is_platform_admin:
            return qs
        # Право — `team.manage` на компании, а не WorkspaceRole OWNER: после ADR-0005 Phase E
        # WorkspaceRole остался слоем ПОДПИСИ и на авторизации не ветвится. Прежняя проверка
        # прятала собственные заявки от делегированного администратора компании, который по
        # правам полностью равен владельцу (у `member_has_permission` есть legacy-ветка на
        # OWNER, поэтому сам владелец ничего не теряет).
        return qs.filter(company_id__in=self._company_ids_user_may_apply_for())

    def _company_ids_user_may_apply_for(self):
        """Компании, за которые этот пользователь вправе подать заявку.

        Тот же предикат, что и в `get_queryset`: кто видит заявки своей компании, тот их и
        подаёт. Разъезд этих двух проверок дал бы список без возможности что-то в него
        добавить — ровно тот класс «показано, но не сработает», который вычищала волна U1.
        """
        user = self.request.user
        return [
            company_id
            for company_id in user.memberships.filter(is_active=True).values_list("company_id", flat=True)
            if member_has_permission(user, company_id, "team.manage")
        ]

    def _resolve_company(self):
        """Чью заявку регистрируем. Считает СЕРВЕР — поле `company` не принимается от клиента.

        Поле сделали read-only при закрытии M2 (владелец компании иначе перевешивал заявку на
        чужого арендатора через PATCH), но `perform_create` продолжал читать его из
        `validated_data` — то есть всегда None. Отсюда мёртвый путь: администратор компании
        получал 403 `ONLY_COMPANY_OWNER_CAN_APPLY` на СВОЮ заявку, а оператор — 500 на NOT NULL.

        Для сотрудника компанию выводим из членств, для оператора платформы (у него членств нет
        по определению) берём явный `company` из запроса — он действует от имени арендатора.
        """
        from rest_framework.exceptions import PermissionDenied, ValidationError

        user = self.request.user
        requested_raw = self.request.data.get("company")

        if user.is_platform_admin:
            if not requested_raw:
                raise ValidationError({"detail": "COMPANY_REQUIRED"})
            company = Company.objects.filter(pk=requested_raw).first()
            if company is None:
                raise ValidationError({"detail": "COMPANY_NOT_FOUND"})
            return company

        allowed_ids = self._company_ids_user_may_apply_for()
        if not allowed_ids:
            raise PermissionDenied("ONLY_COMPANY_OWNER_CAN_APPLY")
        if requested_raw:
            requested_id = int(requested_raw) if str(requested_raw).isdigit() else None
            if requested_id not in allowed_ids:
                raise PermissionDenied("ONLY_COMPANY_OWNER_CAN_APPLY")
            return Company.objects.get(pk=requested_id)
        if len(allowed_ids) > 1:
            # Человек администрирует несколько компаний — угадывать, за какую он подаёт, нельзя.
            raise ValidationError({"detail": "COMPANY_REQUIRED"})
        return Company.objects.get(pk=allowed_ids[0])

    def perform_create(self, serializer):
        serializer.save(company=self._resolve_company(), submitted_by=self.request.user)

    #: Статусы, в которых заявитель ещё может доложить документы. `DOCUMENTS_REQUIRED`
    #: существует ровно для того, чтобы их попросить, — запрещать в нём загрузку значило
    #: делать статус тупиком: оператор просит документы, а приложить их негде.
    _APPLICANT_EDITABLE_STATUSES = ("PENDING", "DOCUMENTS_REQUIRED")

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_platform_admin:
            app = serializer.instance
            if app.status not in self._APPLICANT_EDITABLE_STATUSES:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("APPLICATION_ALREADY_PROCESSED")
        application = serializer.save()
        # Заявитель приложил недостающее — заявка возвращается в очередь на рассмотрение.
        # Так устроен любой цикл «запросили информацию → донесли → снова на проверку»
        # (Stripe verification, Salesforce approval): иначе она молча висит в статусе
        # «нужны документы» и оператор не узнает, что ждать больше нечего.
        if not user.is_platform_admin and application.status == "DOCUMENTS_REQUIRED":
            from ..services.applications import missing_application_documents

            if not missing_application_documents(application):
                application.status = "PENDING"
                application.save(update_fields=["status", "updated_at"])

    @extend_schema(
        summary="Approve role application",
        description="Approve a pending role application. Adds the requested CompanyType to the company.",
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/approve/"""
        app = self.get_object()
        result, error = services.approve_role_application(app, request.user)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)

    @extend_schema(
        summary="Reject role application",
        description="Reject a pending role application with an optional reason.",
        request=inline_serializer(
            "RejectRequest",
            fields={
                "reason": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/reject/"""
        app = self.get_object()
        reason = request.data.get("reason", "")
        result, error = services.reject_role_application(app, request.user, reason)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)

    @extend_schema(
        summary="Request the missing documents instead of rejecting",
        description=(
            "Статус DOCUMENTS_REQUIRED был в модели с самого начала, но поставить его было "
            "нечем: в меню строки жили только «Одобрить» и «Отклонить», и оператору "
            "оставалось закрыть путь целиком. Эталон — Stripe verification «information "
            "needed» и Salesforce «Request more info»."
        ),
        request=inline_serializer("RequestApplicationDocs", fields={"reason": drf_serializers.CharField()}),
        responses={
            200: CompanyRoleApplicationSerializer,
            400: OpenApiResponse(description="ROLE_APPLICATION_CANNOT_REQUEST_DOCS"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="request-documents")
    def request_documents(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/request-documents/"""
        result, error = services.request_application_documents(
            self.get_object(), request.user, reason=request.data.get("reason", "")
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)


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
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    operator_permissions = {
        "list": "billing.view",
        "retrieve": "billing.view",
        "choices": "billing.view",
        "create": "billing.manage",
        "update": "billing.manage",
        "partial_update": "billing.manage",
        "destroy": "billing.manage",
    }
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
