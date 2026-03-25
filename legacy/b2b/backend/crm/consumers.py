import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Enterprise Deal Chat Consumer.
    Room isolation is enforced per deal_id.
    Authentication is checked on connect.
    """

    async def connect(self):
        self.deal_id = self.scope['url_route']['kwargs']['deal_id']
        self.room_group_name = f'chat_deal_{self.deal_id}'
        user = self.scope.get('user')
        from django.contrib.auth.models import AnonymousUser

        # Reject unauthenticated or anonymous users
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4001)
            return

        # Verify the user has access to this deal before joining the room
        has_access = await self.check_deal_access(user, self.deal_id)
        if not has_access:
            await self.close(code=4003)
            return

        # Join the deal's room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """
        Receive message from WebSocket, save to DB, broadcast to room.
        """
        data = json.loads(text_data)
        text = data.get('text', '').strip()
        if not text:
            return

        # Reject oversized messages (max 5000 chars)
        if len(text) > 5000:
            await self.send(text_data=json.dumps({
                'error': 'Message too long (max 5000 characters)'
            }))
            return

        user = self.scope['user']
        message = await self.save_message(user, self.deal_id, text)

        # Broadcast the message to all members of the room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'id': message.id,
                'text': message.text,
                'sender': user.get_full_name() or user.username,
                'sender_id': user.id,
                'timestamp': message.timestamp.isoformat(),
            }
        )

    async def chat_message(self, event):
        """
        Send message to the individual WebSocket connection.
        """
        await self.send(text_data=json.dumps({
            'id': event['id'],
            'text': event['text'],
            'sender': event['sender'],
            'sender_id': event['sender_id'],
            'timestamp': event['timestamp'],
        }))

    @database_sync_to_async
    def check_deal_access(self, user, deal_id):
        from crm.models import Deal
        try:
            deal = Deal.objects.select_related('company').get(pk=deal_id)

            # Staff-level users: check via SystemRole (not is_staff)
            if hasattr(user, 'role') and user.role and user.role.is_staff_level:
                return True
            if user.is_superuser:
                return True

            # Deal manager always has access
            if deal.manager_id == user.id:
                return True

            # Deal client (contact person) always has access
            if deal.client_id == user.id:
                return True

            # B2B: check if user is a member of the deal's company
            if deal.company:
                return user.memberships.filter(
                    company=deal.company, is_active=True
                ).exists()

            return False
        except Deal.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, user, deal_id, text):
        from crm.models import Deal, Message
        deal = Deal.objects.get(pk=deal_id)
        # Enforce message length limit (5000 chars)
        truncated_text = text[:5000]
        return Message.objects.create(deal=deal, sender=user, text=truncated_text)
