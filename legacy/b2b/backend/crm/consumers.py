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
        # Optional buyer-selected lane (which routed seller's thread). A seller derives its
        # own lane server-side and ignores this (audit #4).
        self.requested_lane = self.scope["url_route"]["kwargs"].get("seller_company_id")
        user = self.scope.get("user")
        from django.contrib.auth.models import AnonymousUser

        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            # Accept then close so the browser receives the custom close code
            # (4001) in onclose instead of a generic handshake rejection.
            await self.accept()
            await self.close(code=4001)
            return

        # Resolve the LANE group(s) this user may receive (None = no chat access).
        self.lane_groups = await self.resolve_lane_groups(user, self.deal_id, self.requested_lane)
        if self.lane_groups is None:
            await self.accept()
            await self.close(code=4003)
            return

        for group in self.lane_groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        for group in getattr(self, "lane_groups", []) or []:
            await self.channel_layer.group_discard(group, self.channel_name)

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
                    "seller_company": event.get("seller_company"),
                    "text": event["text"],
                    "sender": event.get("sender"),
                    "sender_name": event.get("sender_name", ""),
                    "message_type": event.get("message_type", "CHAT"),
                    "timestamp": event["timestamp"],
                }
            )
        )

    @database_sync_to_async
    def resolve_lane_groups(self, user, deal_id, requested_lane):
        """The LANE group(s) this user may receive on the deal chat, or None if no access.
        Always the deal-level NULL lane ('all'); PLUS a seller's own routed lane, or the
        buyer's selected (validated) counterparty lane / the sole seller on a 1-seller deal
        (audit #4 — a competing seller is never added to another lane's group)."""
        from accounts.services.permissions import routed_seller_company_id
        from crm.models import Deal
        from crm.services import user_can_access_deal_chat
        from crm.services.messaging import message_lane_group_name

        try:
            deal = Deal.objects.select_related("company").get(pk=deal_id)
        except Deal.DoesNotExist:
            return None
        if not user_can_access_deal_chat(user, deal):
            return None
        groups = [message_lane_group_name(deal_id, None)]
        own = routed_seller_company_id(user, deal_id)
        if own is not None:
            groups.append(message_lane_group_name(deal_id, own))
            return groups
        routed_ids = list(deal.seller_routings.values_list("seller_company_id", flat=True))
        lane = None
        if requested_lane is not None:
            try:
                lane = int(requested_lane) if int(requested_lane) in routed_ids else None
            except (TypeError, ValueError):
                lane = None
        elif len(routed_ids) == 1:
            lane = routed_ids[0]
        if lane is not None:
            groups.append(message_lane_group_name(deal_id, lane))
        return groups

    @database_sync_to_async
    def create_message(self, user, deal_id, text):
        from crm.models import Deal
        from crm.services import send_deal_message

        try:
            deal = Deal.objects.get(pk=deal_id)
        except Deal.DoesNotExist:
            return None, "DEAL_NOT_FOUND"
        # A seller's lane is derived server-side; a buyer sends into its selected lane.
        return send_deal_message(user, deal, text, seller_company_id=self.requested_lane)


class FallbackConsumer(AsyncWebsocketConsumer):
    """
    Catch-all for unknown WebSocket paths.

    Without this, channels' URLRouter raises
    ``ValueError("No route found for path %r.")`` for every path that matches
    no route, which surfaces as an *unhandled* ASGI exception (ERROR log +
    Sentry event) on every reconnect. A stale frontend bundle hammering
    ``/ws/ws/notifications/`` flooded Sentry with 138 such events. We close the
    handshake cleanly (code 4404) instead of raising — no exception, no noise.
    """

    async def connect(self):
        await self.accept()
        await self.close(code=4404)
