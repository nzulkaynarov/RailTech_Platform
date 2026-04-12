from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification
from .serializers import NotificationSerializer
from . import services


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['patch'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        services.mark_notifications_read(Notification.objects.filter(pk=notification.pk))
        return Response({'status': 'notification marked as read'})

    @action(detail=False, methods=['patch'])
    def mark_all_read(self, request):
        count = services.mark_notifications_read(self.get_queryset())
        return Response({'status': 'all notifications marked as read', 'count': count})
