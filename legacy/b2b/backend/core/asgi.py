"""
ASGI config for core project.

Configures Django Channels for WebSocket support (real-time chat)
and standard HTTP requests via Django's ASGI application.
"""

from core.middleware import JwtAuthMiddlewareStack
from crm.routing import websocket_urlpatterns
import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

django_asgi_app = get_asgi_application()


application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        JwtAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
