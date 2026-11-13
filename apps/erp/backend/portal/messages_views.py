"""Чат кабинета (CHAT-1, ADR-0023): `GET/POST /messages`, `POST /messages/read` — модуль `messages`.

Компания и автор — только из сессии (`request.portal_company`, `request.portal_contact`), из тела — никогда. Логика —
`portal/services/messages.py`; форма ответа — `PortalMessage`/`PortalMessagePage` контракта `erp-portal.yaml`.
"""

from __future__ import annotations

from django.http import Http404
from portal.exceptions import PortalValidationError
from portal.models import PortalMessage
from portal.permissions import HasPortalModule, IsPortalAuthenticated
from portal.serializers import (
    PortalMessageCreateSerializer,
    PortalMessageReadMarkSerializer,
    deal_stages,
    portal_message_data,
)
from portal.services import messages as chat
from portal.views import BasePortalView
from rest_framework import status
from rest_framework.response import Response

MODULE = "messages"


def _int_param(request, name: str, default=None, *, low: int = 0, high: int | None = None):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise PortalValidationError("VALIDATION_ERROR") from None
    if value < low or (high is not None and value > high):
        raise PortalValidationError("VALIDATION_ERROR")
    return value


class MessageListView(BasePortalView):
    """GET /messages — лента компании (с `after_id` — новые); POST /messages — написать менеджеру (`can_act`)."""

    required_module = MODULE

    def get(self, request):
        after_id = _int_param(request, "after_id")
        limit = _int_param(request, "limit", 50, low=1, high=chat.MAX_PAGE)
        items, has_more = chat.feed(request.portal_company, after_id=after_id, limit=limit)
        chat.touch_presence(request.portal_company, request.portal_contact)
        me = request.portal_contact.pk
        erased = chat.erased_ids(request.portal_company, up_to=after_id) if after_id is not None else []
        stages = deal_stages(items)
        return Response(
            {"items": [portal_message_data(m, me, stages) for m in items], "has_more": has_more, "erased_ids": erased}
        )

    def post(self, request):
        serializer = PortalMessageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        text = data["text"].strip()
        if not text:
            raise PortalValidationError("TEXT_REQUIRED")
        try:
            message, created = chat.post_message(
                request.portal_company,
                request.portal_contact,
                text=text,
                client_message_id=data["client_message_id"],
                context=data.get("context"),
                modules=request.portal_modules,
            )
        except chat.ContextNotFound:
            raise Http404 from None
        body = portal_message_data(message, request.portal_contact.pk)
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MessageReadView(BasePortalView):
    """POST /messages/read — отметка «прочитано» контактом сессии; `can_act` не нужен (это чтение)."""

    required_module = MODULE
    permission_classes = [IsPortalAuthenticated, HasPortalModule]

    def post(self, request):
        serializer = PortalMessageReadMarkSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        try:
            unread = chat.mark_read(
                request.portal_company, request.portal_contact, serializer.validated_data["last_id"]
            )
        except PortalMessage.DoesNotExist:
            raise Http404 from None
        return Response({"unread": unread})
