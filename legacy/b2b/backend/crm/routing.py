from django.urls import re_path

from notifications.consumers import NotificationConsumer

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/chat/(?P<deal_id>\d+)/$", consumers.ChatConsumer.as_asgi()),
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
    # Catch-all — MUST stay last. Unknown WS paths close cleanly via
    # FallbackConsumer instead of raising ValueError in URLRouter (which would
    # log an unhandled ASGI ERROR + emit a Sentry event on every reconnect).
    re_path(r".*", consumers.FallbackConsumer.as_asgi()),
]
