"""
ASGI config for core project.

Configures Django Channels for WebSocket support (real-time notifications)
and standard HTTP requests via Django's ASGI application.
"""

import os

import django
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

from core.console_mount import ConsolePrefixMount, console_prefix
from core.middleware import JwtAuthMiddlewareStack
from crm.routing import websocket_urlpatterns

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

django_asgi_app = get_asgi_application()


application = ProtocolTypeRouter(
    {
        # Django admin под /console/erp на домене Платформы (OPS-CONSOLE): core/console_mount.py.
        "http": ConsolePrefixMount(django_asgi_app, console_prefix()),
        "websocket": AllowedHostsOriginValidator(JwtAuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
    }
)
