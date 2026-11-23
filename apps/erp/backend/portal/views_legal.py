"""Оферта и политика Кабинета (ДВ-5): `GET /legal`, `POST /legal/accept`, публичный `GET /legal/policy`.

`/legal` и `/legal/accept` открыты и сессии без акцепта (`legal_exempt`) — иначе принять было бы нечем; права «действовать»
не требуют: принять текст может любой контакт, в том числе с доступом только на чтение. Логика — `portal/services/legal.py`.
"""

from portal.authentication import PortalAuthentication
from portal.client_ip import client_ip
from portal.exceptions import PortalValidationError, portal_exception_handler
from portal.permissions import IsPortalAuthenticated
from portal.services import legal
from portal.throttles import PortalSessionRateThrottle
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView


class LegalAcceptSerializer(serializers.Serializer):
    edition_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=len(legal.KINDS)
    )
    language = serializers.ChoiceField(choices=legal.LANGUAGES)


class _PortalLegalView(APIView):
    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalAuthenticated]
    throttle_classes = [PortalSessionRateThrottle]
    #: Принять документы можно и без акцепта: на этих вьюхах `IsPortalAuthenticated` кабинет не закрывает.
    legal_exempt = True

    def get_exception_handler(self):
        return portal_exception_handler


class LegalCurrentView(_PortalLegalView):
    """GET /legal — действующие редакции для контакта сессии с признаком «нужно принять»."""

    def get(self, request):
        return Response(legal.current_for_contact(request.portal_contact.pk), headers={"Cache-Control": "no-store"})


class LegalAcceptView(_PortalLegalView):
    """POST /legal/accept — принять действующие редакции, которые контакт видел на экране."""

    def post(self, request):
        body = LegalAcceptSerializer(data=request.data)
        if not body.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        result = legal.accept(
            request.portal_session,
            body.validated_data["edition_ids"],
            body.validated_data["language"],
            ip=client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(result)


class LegalPolicyView(APIView):
    """GET /legal/policy — действующая политика для экрана входа (до входа). `policy: null` — ещё не опубликована."""

    authentication_classes = []
    permission_classes = []

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request):
        return Response({"policy": legal.public_policy()})
