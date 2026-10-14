from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.audit import AuditedWriteMixin
from core.permissions import ADMIN_ONLY, IsPlatformAdmin, RoleGatedViewMixin

from . import services, services_email_templates
from .models import EmailTemplate, Notification
from .serializers import (
    EmailTemplatePreviewSerializer,
    EmailTemplateSerializer,
    EmailTemplateTestSendSerializer,
    NotificationSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="List notifications",
        description="Returns all notifications for the current user.",
        tags=["Notifications"],
    ),
    retrieve=extend_schema(
        summary="Get notification",
        description="Returns a single notification by ID.",
        tags=["Notifications"],
    ),
)
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only notifications for the current user.

    Includes actions to mark individual or all notifications as read.
    """

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        from django.db.models import Q

        user = self.request.user
        # Аудитория видимости: USER-канал — только для не-админов; PLATFORM_ADMIN-канал — только
        # для Platform Admin. Админ НЕ видит клиентские уведомления; USER НЕ видит platform-алёрты.
        if user.is_superuser:
            audience = Notification.AUDIENCE_PLATFORM_ADMIN
        else:
            audience = Notification.AUDIENCE_USER
        return Notification.objects.select_related("type").filter(
            Q(audience=audience) & (Q(user=user) | Q(user__isnull=True))
        )

    @extend_schema(
        summary="Mark notification as read",
        description="Mark a single notification as read by its ID.",
        responses={200: OpenApiResponse(description="Notification marked as read")},
        tags=["Notifications"],
    )
    @action(detail=True, methods=["patch"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        services.mark_notifications_read(Notification.objects.filter(pk=notification.pk))
        return Response({"status": "notification marked as read"})

    @extend_schema(
        summary="Mark all notifications as read",
        description="Mark all of the current user's notifications as read.",
        responses={200: OpenApiResponse(description="All notifications marked as read")},
        tags=["Notifications"],
    )
    @action(detail=False, methods=["patch"])
    def mark_all_read(self, request):
        count = services.mark_notifications_read(self.get_queryset())
        return Response(
            {
                "status": "all notifications marked as read",
                "count": count,
            }
        )


@extend_schema_view(
    list=extend_schema(summary="List email templates", tags=["Admin"]),
    retrieve=extend_schema(summary="Get email template", tags=["Admin"]),
    create=extend_schema(summary="Create email template", tags=["Admin"]),
    update=extend_schema(summary="Update email template", tags=["Admin"]),
    partial_update=extend_schema(summary="Patch email template", tags=["Admin"]),
    destroy=extend_schema(summary="Delete email template", tags=["Admin"]),
)
class EmailTemplateViewSet(RoleGatedViewMixin, AuditedWriteMixin, viewsets.ModelViewSet):
    """Platform-Operator CRUD for DB-editable email templates.

    An active row here overrides the file template of the same key when
    `notifications.emails.send_templated_email` renders. Thin wrapper — preview
    and test-send delegate to `services_email_templates`.
    """

    required_permissions = {
        "create": ADMIN_ONLY,
        "update": ADMIN_ONLY,
        "partial_update": ADMIN_ONLY,
        "destroy": ADMIN_ONLY,
        "preview": ADMIN_ONLY,
        "test_send": ADMIN_ONLY,
    }

    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    # Суб-способность оператора, а не «любой платформенный админ» (ADR-0004 G1, least privilege).
    #
    # Раньше стоял голый `IsPlatformAdmin`: оператор «Поддержка», заведённый как ТОЛЬКО ПРОСМОТР,
    # создавал, правил и УДАЛЯЛ шаблоны писем. Активная строка здесь немедленно подменяет файловый
    # шаблон ДЛЯ ВСЕХ получателей — то есть это произвольный HTML в письме клиенту от имени
    # платформы, — а `test-send` реально отправляет письмо и пишет `EmailLog`. Пункт меню был
    # скрыт по праву `platform.settings`, но переход по адресу правом не закрывался, и за скрытой
    # дверью не стояло ничего (прогон 20-08). Тот же образец уже применён в `catalog/views/lookups.py`.
    #
    # `IsPlatformAdmin` резолвит право по `action`, поэтому кастомные `preview` и `test-send`
    # накрываются тем же дефолтом — их открытыми оставлять нельзя.
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]

    #: Активная строка НЕМЕДЛЕННО подменяет файловый шаблон для ВСЕХ получателей платформы:
    #: текст, который увидит каждый арендатор в письме о счёте или об акте. Поле `updated_by`
    #: отвечает «кто последний», но не «что было раньше» и в «Журнал доступа» не попадает.
    audit_event_prefix = "email_template"

    def audit_action(self, instance, event: str) -> str:
        return f"Шаблон письма {event}: {instance.key}"

    def audit_snapshot(self, instance):
        return {
            "key": instance.key,
            "subject": instance.subject,
            "is_active": instance.is_active,
            "language": instance.language,
        }

    def audit_event_params(self, instance) -> dict:
        return {"key": instance.key}

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)
        self._write_audit(serializer.instance, "created", after=self.audit_snapshot(serializer.instance))

    def perform_update(self, serializer):
        before = self.audit_snapshot(serializer.instance)
        serializer.save(updated_by=self.request.user)
        self._write_audit(serializer.instance, "updated", before=before, after=self.audit_snapshot(serializer.instance))

    @extend_schema(
        summary="Preview email template",
        description="Render the template's subject/html/text against a SAMPLE context (or a "
        "provided override context). Does NOT send. Reflects DB override vs file fallback.",
        request=EmailTemplatePreviewSerializer,
        responses={200: OpenApiResponse(description="Rendered subject/text_body/html_body")},
        tags=["Admin"],
    )
    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        template = self.get_object()
        serializer = EmailTemplatePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        override_context = serializer.validated_data.get("context")
        result = services_email_templates.preview_template(template.key, context=override_context)
        return Response(result)

    @extend_schema(
        summary="Send a test email",
        description="Render the template and send it to the provided email via the real pipeline. "
        "Writes an EmailLog. Use to verify copy and transport before going live.",
        request=EmailTemplateTestSendSerializer,
        responses={200: OpenApiResponse(description="Send result with EmailLog id and status")},
        tags=["Admin"],
    )
    @action(detail=True, methods=["post"], url_path="test-send")
    def test_send(self, request, pk=None):
        template = self.get_object()
        serializer = EmailTemplateTestSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = services_email_templates.test_send_template(
            template.key,
            serializer.validated_data["to_email"],
            user=request.user,
            context=serializer.validated_data.get("context"),
        )
        return Response(
            {
                "status": log.status if log else "UNKNOWN",
                "email_log_id": log.id if log else None,
                "to_email": serializer.validated_data["to_email"],
            }
        )
