from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import services
from core.models import SupportTicket, SupportTicketMessage

# ──────────────────────────────────────────────────────────────────────────
# System Settings (singleton)
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# Support tickets — прямой канал связи клиента с Platform Admin.
# ──────────────────────────────────────────────────────────────────────────


class SupportTicketMessageSerializer(drf_serializers.ModelSerializer):
    author_email = drf_serializers.CharField(source="author.email", read_only=True)
    author_full_name = drf_serializers.SerializerMethodField()
    author_is_admin = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketMessage
        fields = [
            "id",
            "ticket",
            "text",
            "is_internal",
            "author",
            "author_email",
            "author_full_name",
            "author_is_admin",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "author",
            "author_email",
            "author_full_name",
            "author_is_admin",
            "created_at",
        ]

    def get_author_full_name(self, obj: SupportTicketMessage) -> str:
        if not obj.author:
            return ""
        return obj.author.get_full_name() or obj.author.email

    def get_author_is_admin(self, obj: SupportTicketMessage) -> bool:
        return bool(obj.author and obj.author.is_superuser)


class SupportTicketSerializer(drf_serializers.ModelSerializer):
    created_by_email = drf_serializers.CharField(source="created_by.email", read_only=True)
    created_by_full_name = drf_serializers.SerializerMethodField()
    company_name = drf_serializers.CharField(source="company.name", read_only=True)
    assigned_to_email = drf_serializers.CharField(source="assigned_to.email", read_only=True)
    messages_count = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "description",
            "category",
            "priority",
            "status",
            "created_by",
            "created_by_email",
            "created_by_full_name",
            "company",
            "company_name",
            "assigned_to",
            "assigned_to_email",
            "messages_count",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_email",
            "created_by_full_name",
            "company",
            "company_name",
            "assigned_to",
            "assigned_to_email",
            "messages_count",
            "created_at",
            "updated_at",
            "resolved_at",
        ]

    def get_created_by_full_name(self, obj: SupportTicket) -> str:
        if not obj.created_by:
            return ""
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_messages_count(self, obj: SupportTicket) -> int:
        return getattr(obj, "messages_count_db", obj.messages.count())


@extend_schema_view(
    list=extend_schema(summary="List support tickets", tags=["Support"]),
    retrieve=extend_schema(summary="Get support ticket", tags=["Support"]),
    create=extend_schema(summary="Create support ticket", tags=["Support"]),
    partial_update=extend_schema(summary="Update support ticket (admin)", tags=["Support"]),
    destroy=extend_schema(summary="Delete support ticket (admin)", tags=["Support"]),
)
class SupportTicketViewSet(viewsets.ModelViewSet):
    """
    Канал прямой связи: любой пользователь создаёт тикет, Platform Admin
    ведёт переписку и меняет статус.

    - пользователь: видит свои тикеты, может создавать и отвечать;
    - Platform Admin: видит все тикеты, меняет статус, назначает исполнителя,
      оставляет внутренние заметки (is_internal=True).
    """

    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        "status": ["exact", "in"],
        "priority": ["exact", "in"],
        "category": ["exact", "in"],
        "assigned_to": ["exact"],
        "company": ["exact"],
    }
    search_fields = ["subject", "description", "created_by__email"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportTicket.objects.none()
        qs = SupportTicket.objects.select_related(
            "created_by",
            "company",
            "assigned_to",
        ).annotate(messages_count_db=Count("messages"))
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        data = serializer.validated_data
        ticket = services.create_support_ticket(
            author=self.request.user,
            subject=data["subject"],
            description=data["description"],
            category=data.get("category", SupportTicket.CATEGORY_QUESTION),
            priority=data.get("priority", SupportTicket.PRIORITY_NORMAL),
        )
        serializer.instance = ticket

    def perform_update(self, serializer):
        if not self.request.user.is_superuser:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_superuser:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        instance.delete()

    @extend_schema(
        summary="List ticket messages",
        responses={200: SupportTicketMessageSerializer(many=True)},
        tags=["Support"],
    )
    @extend_schema(
        summary="Counters over the WHOLE filtered selection, not the current page",
        description=(
            "Плитки экрана поддержки считались по `data.results` — то есть по ОДНОЙ странице "
            "из двадцати строк, тогда как рядом `Всего` бралось из `count`. При 57 тикетах "
            "экран показывал «Открытых 20» и «Срочных 0», хотя срочные лежали на страницах "
            "2 и 3. Счётчики обязаны считаться по той же выборке, что и список — со всеми "
            "фильтрами и поиском, но без постраничного среза."
        ),
        responses={200: OpenApiResponse(description="{total, open, in_progress, urgent}")},
        tags=["Core"],
    )
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """GET /api/v1/support-tickets/stats/ — счётчики по ВСЕЙ выборке.

        Один `aggregate` вместо четырёх `.count()`: реестр дорастёт до тысяч строк, и
        отдельные запросы в цикле здесь превратились бы в задержку на каждый рендер
        (конвенция производительности проекта).
        """
        queryset = self.filter_queryset(self.get_queryset())
        totals = queryset.aggregate(
            total=Count("id"),
            open=Count("id", filter=Q(status=SupportTicket.STATUS_OPEN)),
            in_progress=Count("id", filter=Q(status=SupportTicket.STATUS_IN_PROGRESS)),
            urgent=Count(
                "id",
                filter=Q(priority=SupportTicket.PRIORITY_URGENT)
                & ~Q(status__in=[SupportTicket.STATUS_CLOSED, SupportTicket.STATUS_RESOLVED]),
            ),
        )
        return Response(totals)

    @action(detail=True, methods=["get"], url_path="messages")
    def list_messages(self, request, pk=None):
        ticket = self.get_object()
        qs = ticket.messages.select_related("author").order_by("created_at")
        if not request.user.is_superuser:
            qs = qs.filter(is_internal=False)
        serializer = SupportTicketMessageSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Add ticket message",
        request=SupportTicketMessageSerializer,
        responses={201: SupportTicketMessageSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="add-message")
    def add_message(self, request, pk=None):
        ticket = self.get_object()
        text = (request.data.get("text") or "").strip()
        if not text:
            raise ValidationError({"text": "SUPPORT_MESSAGE_TEXT_REQUIRED"})
        is_internal = bool(request.data.get("is_internal", False))
        if is_internal and not request.user.is_superuser:
            raise PermissionDenied("SUPPORT_INTERNAL_NOTE_ADMIN_ONLY")
        message = services.add_ticket_message(
            ticket=ticket,
            author=request.user,
            text=text,
            is_internal=is_internal,
        )
        return Response(
            SupportTicketMessageSerializer(message).data,
            status=201,
        )

    @extend_schema(
        summary="Change ticket status (admin)",
        responses={200: SupportTicketSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        ticket = self.get_object()
        status_code = request.data.get("status")
        updated = services.change_ticket_status(
            ticket=ticket,
            status=status_code,
            actor=request.user,
        )
        if updated is None:
            raise ValidationError({"status": "SUPPORT_INVALID_STATUS"})
        return Response(SupportTicketSerializer(updated).data)

    @extend_schema(
        summary="Assign ticket to Platform Admin",
        responses={200: SupportTicketSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        if not request.user.is_superuser:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        ticket = self.get_object()
        from accounts.models import CustomUser

        assignee_id = request.data.get("assigned_to")
        if assignee_id is None:
            assignee = request.user
        else:
            try:
                assignee = CustomUser.objects.get(pk=assignee_id)
            except CustomUser.DoesNotExist:
                raise ValidationError({"assigned_to": "SUPPORT_ASSIGNEE_NOT_FOUND"})
            if not assignee.is_superuser:
                raise ValidationError({"assigned_to": "SUPPORT_ASSIGNEE_NOT_ADMIN"})
        updated = services.assign_ticket(ticket=ticket, assignee=assignee)
        return Response(SupportTicketSerializer(updated).data)
