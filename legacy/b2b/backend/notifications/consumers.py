"""
User-scoped WebSocket consumer for realtime in-app notifications.

Each authenticated user joins a private group `notifications_<user_id>`.
notifications.services.push_notification_ws already broadcasts to this group
whenever a Notification is created, so the consumer only needs to forward
those events down to the client.
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        from django.contrib.auth.models import AnonymousUser

        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            # Accept then close so the browser receives the custom close code
            # (4001) in onclose instead of a generic handshake rejection.
            await self.accept()
            await self.close(code=4001)
            return

        self.user_id = user.id
        self.group_name = f"notifications_{self.user_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_push(self, event):
        """Channel-layer handler: relay the payload to the client socket."""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification",
                    "data": event.get("data", {}),
                }
            )
        )
