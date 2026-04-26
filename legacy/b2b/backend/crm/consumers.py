import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Deal chat consumer.

    Room isolation is enforced per deal_id. Auth is verified on connect via
    the JwtAuthMiddleware (scope['user']). Messages are saved through
    crm.services.send_deal_message; broadcast is handled by the post_save
    signal, so the consumer never group_sends by itself.
    """

    async def connect(self):
        self.deal_id = self.scope["url_route"]["kwargs"]["deal_id"]
        self.room_group_name = f"chat_deal_{self.deal_id}"
        user = self.scope.get("user")
        from django.contrib.auth.models import AnonymousUser

        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4001)
            return

        has_access = await self.check_deal_access(user, self.deal_id)
        if not has_access:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name,
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            return
        text = (data.get("text") or "").strip()
        if not text:
            return

        user = self.scope["user"]
        message, error = await self.create_message(user, self.deal_id, text)
        if error:
            await self.send(text_data=json.dumps({"error": error}))

    async def chat_message(self, event):
        """Forward a Message payload (broadcast by post_save signal) to the client."""
        await self.send(
            text_data=json.dumps(
                {
                    "id": event["id"],
                    "deal": event.get("deal"),
                    "text": event["text"],
                    "sender": event.get("sender"),
                    "sender_name": event.get("sender_name", ""),
                    "message_type": event.get("message_type", "CHAT"),
                    "timestamp": event["timestamp"],
                }
            )
        )

    @database_sync_to_async
    def check_deal_access(self, user, deal_id):
        from crm.models import Deal
        from crm.services import user_can_access_deal_chat

        try:
            deal = Deal.objects.select_related("company").get(pk=deal_id)
        except Deal.DoesNotExist:
            return False
        return user_can_access_deal_chat(user, deal)

    @database_sync_to_async
    def create_message(self, user, deal_id, text):
        from crm.models import Deal
        from crm.services import send_deal_message

        try:
            deal = Deal.objects.get(pk=deal_id)
        except Deal.DoesNotExist:
            return None, "DEAL_NOT_FOUND"
        return send_deal_message(user, deal, text)
