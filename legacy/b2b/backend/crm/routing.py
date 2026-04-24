from django.urls import re_path
from . import consumers
from notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<deal_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/notifications/$', NotificationConsumer.as_asgi()),
]
