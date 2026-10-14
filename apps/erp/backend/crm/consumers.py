from channels.generic.websocket import AsyncWebsocketConsumer


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
