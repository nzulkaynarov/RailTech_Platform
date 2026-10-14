"""Tests for the WebSocket routing table (crm.routing).

Redis-free: inspects routing only. The deal-chat consumer was removed in M1-ERP-02
(wave 1b) — the only CRM-side consumer left is the catch-all FallbackConsumer.
"""


class TestWebsocketFallbackRoute:
    """Regression guard for the ws/ws/notifications/ Sentry flood (138 events).

    An unknown WebSocket path must route to FallbackConsumer (which closes the
    handshake cleanly) instead of falling through URLRouter and raising
    ValueError('No route found for path ...'). Redis-free: inspects routing.
    """

    def test_catchall_is_last_and_matches_unknown_path(self):
        from crm.consumers import FallbackConsumer
        from crm.routing import websocket_urlpatterns

        last = websocket_urlpatterns[-1]
        # as_asgi() stores the consumer class on the returned app
        assert last.callback.consumer_class is FallbackConsumer
        # it must match the exact path that flooded Sentry, plus any junk
        assert last.pattern.regex.match("ws/ws/notifications/") is not None
        assert last.pattern.regex.match("anything/else/") is not None

    def test_known_paths_precede_fallback(self):
        from crm.routing import websocket_urlpatterns

        # real routes come BEFORE the catch-all so they win the match
        assert len(websocket_urlpatterns) >= 2
        earlier = [p.pattern.regex.pattern for p in websocket_urlpatterns[:-1]]
        assert any("notifications" in r for r in earlier)
