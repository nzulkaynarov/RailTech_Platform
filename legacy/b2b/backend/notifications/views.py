from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from .models import Notification
from .serializers import NotificationSerializer
from . import services


@extend_schema_view(
    list=extend_schema(
        summary="List notifications",
        description="Returns all notifications for the current user.",
        tags=['Notifications'],
    ),
    retrieve=extend_schema(
        summary="Get notification",
        description="Returns a single notification by ID.",
        tags=['Notifications'],
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
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.none()
        from django.db.models import Q
        return Notification.objects.filter(
            Q(user=self.request.user) | Q(user__isnull=True)
        )

    @extend_schema(
        summary="Mark notification as read",
        description="Mark a single notification as read by its ID.",
        responses={200: OpenApiResponse(description="Notification marked as read")},
        tags=['Notifications'],
    )
    @action(detail=True, methods=['patch'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        services.mark_notifications_read(
            Notification.objects.filter(pk=notification.pk)
        )
        return Response({'status': 'notification marked as read'})

    @extend_schema(
        summary="Mark all notifications as read",
        description="Mark all of the current user's notifications as read.",
        responses={200: OpenApiResponse(description="All notifications marked as read")},
        tags=['Notifications'],
    )
    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        count = services.mark_notifications_read(self.get_queryset())
        return Response({
            'status': 'all notifications marked as read',
            'count': count,
        })
