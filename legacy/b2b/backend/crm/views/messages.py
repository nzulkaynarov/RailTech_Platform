from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin, IsPlatformAdmin
from crm.models import ActivityLog, Deal, Message
from crm.serializers import ActivityLogSerializer, MessageSerializer
from crm.services import send_deal_message


@extend_schema_view(
    list=extend_schema(
        summary="List messages",
        description="Returns deal messages. Filterable by deal_id.",
        tags=["CRM"],
    ),
    create=extend_schema(
        summary="Send message",
        description="Send a message in a deal chat. Sender is auto-assigned.",
        tags=["CRM"],
    ),
    retrieve=extend_schema(summary="Get message", tags=["CRM"]),
    update=extend_schema(summary="Update message", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update message", tags=["CRM"]),
    destroy=extend_schema(summary="Delete message", tags=["CRM"]),
)
class MessageViewSet(viewsets.ModelViewSet):
    """
    CRUD for deal messages (chat within a deal).

    Messages are ordered by timestamp. The sender is auto-assigned
    to the current user on creation.
    """

    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_fields = ["deal", "deal_id", "message_type"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        user = self.request.user
        queryset = Message.objects.all().order_by("timestamp").select_related("sender", "deal")

        from accounts.services.permissions import seller_visible_deal_ids

        # A seller acting in seller context sees the chat on every deal it works
        # (parity with DealViewSet/QuoteViewSet). In BUYER context the same user is
        # scoped to its own deals — no cross-tenant chat. Without the see-all branch
        # a seller who isn't the specific deal.manager saw the deal + КП but NOT its
        # chat. Platform admin is covered by the is_platform_admin branch.
        if getattr(user, "is_platform_admin", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            return queryset.filter(deal_id__in=visible_deal_ids)

        # Buyer: only messages on deals owned by a company the user is a member of
        # (plus deals where they are personally the manager/client). No cross-tenant.
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(
            Q(deal__company_id__in=user_company_ids) | Q(deal__manager_id=user.id) | Q(deal__client_id=user.id)
        ).distinct()

    def create(self, request, *args, **kwargs):
        deal_id = request.data.get("deal")
        text = request.data.get("text", "")
        if not deal_id:
            return Response(
                {"detail": "deal is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            deal = Deal.objects.get(pk=deal_id)
        except Deal.DoesNotExist:
            return Response(
                {"detail": "DEAL_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )
        message, error = send_deal_message(request.user, deal, text)
        if error == "NOT_DEAL_MEMBER":
            return Response({"detail": error}, status=status.HTTP_403_FORBIDDEN)
        if error == "EMPTY_MESSAGE":
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        if error or message is None:
            return Response(
                {"detail": error or "UNKNOWN_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = MessageSerializer(message, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(
        summary="List activity logs",
        description=("Returns activity logs. Superusers see all; " "managers see only their own logs."),
        tags=["CRM"],
    ),
    retrieve=extend_schema(summary="Get activity log entry", tags=["CRM"]),
)
class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to activity logs for audit trail."""

    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get_queryset(self):
        """Staff see all logs. Non-admin managers see only their own."""
        user = self.request.user
        queryset = ActivityLog.objects.all().select_related("user")
        if user.is_superuser:
            return queryset
        return queryset.filter(user=user)
