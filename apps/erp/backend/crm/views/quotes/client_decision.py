"""«Клиент принял / отклонил КП» по подтверждению клиента (A1 волны 18a) — действие `QuoteViewSet`.

Тонкая обёртка (CONVENTIONS.md §5): право `deal.manage` объявлено во вьюсете (`required_permissions`), поля, файл, статус
и ядро акцепта или отказа — `crm.services.quotes.client_decision`.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm.serializers import QuoteSerializer
from crm.services.quotes.on_behalf import CHANNELS, COMMENT_MAX, PERSON_MAX


class ClientDecisionInSerializer(drf_serializers.Serializer):
    decision = drf_serializers.ChoiceField(choices=["accept", "reject"])
    channel = drf_serializers.ChoiceField(choices=list(CHANNELS), help_text="Как клиент сообщил решение")
    counterparty_person = drf_serializers.CharField(max_length=PERSON_MAX, help_text="Кто со стороны клиента")
    occurred_on = drf_serializers.DateField(help_text="Когда клиент сообщил решение; не позже сегодня")
    comment = drf_serializers.CharField(max_length=COMMENT_MAX, help_text="Суть ответа клиента; для отказа — причина")
    file = drf_serializers.FileField(help_text="Подтверждение клиента: письмо, переписка, скан (до 20 МБ)")


class QuoteClientDecisionMixin:
    """`POST /crm/quotes/{id}/record-client-decision/` для `QuoteViewSet`."""

    @extend_schema(
        summary="Записать решение клиента по отправленному КП по его подтверждению (A1, «Отметить за контрагента»)",
        description=(
            "Клиент принял или отклонил КП не в кабинете, а письмом, в переписке, по телефону, лично или на бумаге. "
            "Файл подтверждения обязателен (изображение, PDF, doc, docx, xls, xlsx, csv, txt до 20 МБ). Только КП в "
            "статусе SENT; дальше — то же ядро, что онлайн-акцепт и отказ клиента (стадия, проект, договор, резерв, "
            "события `quote.accepted` / `quote.rejected` с `recorded_by_staff`, уведомления). Право `deal.manage`."
        ),
        request={"multipart/form-data": ClientDecisionInSerializer},
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(
                description=(
                    "DECISION_INVALID / CHANNEL_INVALID / COUNTERPARTY_PERSON_REQUIRED / COMMENT_REQUIRED / "
                    "OCCURRED_ON_INVALID / OCCURRED_ON_IN_FUTURE / EVIDENCE_REQUIRED / EVIDENCE_INVALID"
                )
            ),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
            404: OpenApiResponse(description="QUOTE_NOT_FOUND"),
            409: OpenApiResponse(description="QUOTE_NOT_SENT / DEAL_STAGE_CONFLICT"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="record-client-decision",
        permission_classes=[IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser],
    )
    def record_client_decision(self, request, pk=None):
        from crm.services.quotes.client_decision import HTTP_STATUS, ClientDecisionInput, record_client_decision

        data = request.data

        def text(name: str) -> str:
            value = data.get(name)
            return value if isinstance(value, str) else ""

        quote, error = record_client_decision(
            int(pk),
            request.user,
            ClientDecisionInput(
                decision=text("decision"),
                channel=text("channel"),
                counterparty_person=text("counterparty_person"),
                occurred_on=text("occurred_on"),
                comment=text("comment"),
                evidence=request.FILES.get("file"),
            ),
        )
        if error:
            return Response({"detail": error}, status=HTTP_STATUS.get(error, status.HTTP_400_BAD_REQUEST))
        quote = self.get_queryset().get(pk=quote.pk)
        return Response(self.get_serializer(quote).data)
