from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsPlatformAdmin
from crm.models import ActivityLog
from crm.serializers import ActivityLogSerializer


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
        """The audit trail is a platform-moderation surface (IsPlatformAdmin gates the
        viewset): every platform admin sees all logs. ARCH-09: the old is_superuser
        branch left non-superuser platform operators seeing only their own actions —
        the wrong privilege model for an audit endpoint."""
        if getattr(self, "swagger_fake_view", False):
            return ActivityLog.objects.none()
        user = self.request.user
        queryset = ActivityLog.objects.all().select_related("user")
        if getattr(user, "is_superuser", False):
            return queryset
        return queryset.filter(user=user)
