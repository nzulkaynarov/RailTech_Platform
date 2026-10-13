"""Справочник стадий сделки (read-only lookup)."""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm.models import DealStage

# Экшены, открывающие ОДНУ конкретную сделку (read-only). Видимость у них шире списочной:
# продавец вправе открыть сделку, где он покупатель, и наоборот. Раньше это условие было
# записано литералом `self.action == "retrieve"` в двух местах get_queryset, поэтому КАЖДЫЙ
# новый detail-экшен молча получал списочный скоуп и отдавал 404 там, где retrieve отдаёт 200.
# Набор намеренно ограничен читающими экшенами: расширять скоуп пишущим — менять границу
# безопасности.
SINGLE_DEAL_READ_ACTIONS = frozenset({"retrieve", "documents"})


class DealStageLookupSerializer(drf_serializers.Serializer):
    """Response shape for the DealStage lookup feed ({code, name})."""

    code = drf_serializers.CharField()
    name = drf_serializers.CharField()


@extend_schema_view(
    list=extend_schema(summary="List deal stages", tags=["CRM"]),
)
class DealStageViewSet(viewsets.ReadOnlyModelViewSet):
    # Только активные этапы: выведенный из эксплуатации (KYC_PENDING, is_active=False) исчезает
    # из дропдауна/Канбана/воронки сам — источники этапов на фронте едины (useDealStages).
    queryset = DealStage.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = DealStageLookupSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"code": s.code, "name": s.name} for s in self.get_queryset()]
        return Response(data)
