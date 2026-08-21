from django.core.cache import cache
from django.utils.translation import get_language
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import Country, Currency, DeliveryBasis, HSCode, UnitOfMeasure
from .serializers import CountrySerializer, CurrencySerializer, DeliveryBasisSerializer, UnitOfMeasureSerializer


def _lookup_write_permissions(view):
    """Чтение справочника — публичное, ЗАПИСЬ — по суб-способности `platform.settings`.

    Раньше на всех четырёх вьюсетах стоял голый `IsPlatformAdminOrReadOnly`, проверяющий лишь
    «оператор платформы вообще». Оператор «Поддержка», заведённый как ТОЛЬКО ПРОСМОТР, создавал,
    правил и удалял валюты, страны и единицы измерения — а они печатаются в документах ВСЕХ
    арендаторов (прогон 20-08). Пункт меню был скрыт по праву, но за скрытой дверью не стояло
    ничего: переход по адресу правом не закрывался.

    Образец не новый — ровно так уже сделано в `catalog/views/lookups.py` волной N3, с тем же
    выводом в комментарии: «раньше писала ЛЮБАЯ суб-роль оператора, включая SUPPORT „только
    просмотр“». Здесь тот же приём, чтобы механика была одна, а не две.

    Публичное чтение сохраняем: списки справочников читают почти все экраны, включая
    неавторизованные (публичная страница КП).
    """
    if getattr(view, "action", None) in ("list", "retrieve"):
        return [permissions.AllowAny()]
    from core.permissions import OperatorScoped

    return [OperatorScoped()]


LOOKUP_CACHE_TTL = 60 * 10  # 10 min — справочники меняются редко


class _CachedLookupListMixin:
    """Кэш списка справочника, который СБРАСЫВАЕТСЯ правкой.

    До 20-08 здесь стоял `cache_page(600)` на `list` — и тот же вьюсет выполнял запись. Оператор
    переименовывал валюту, сохранял, список отдавал прежнюю страницу ещё до десяти минут, и
    правка выглядела пропавшей. Ровно тот класс «сделал — не видно», из-за которого путь
    считается мёртвым, хотя запрос прошёл.

    Ключ несёт номер редакции справочника; запись его увеличивает, и старые страницы перестают
    находиться. Так же устроена инвалидация по версии в Odoo (`ormcache` сбрасывается на write)
    и в Rails (cache key от `updated_at`) — берём тот же приём, а не «убрать кэш вовсе»: список
    справочника читают почти все экраны.
    """

    @property
    def _model_label(self) -> str:
        return self.queryset.model._meta.label_lower

    def _version(self) -> int:
        return cache.get(f"lookup-version:{self._model_label}", 1)

    def _bump_version(self) -> None:
        key = f"lookup-version:{self._model_label}"
        # Не `cache.incr`: он падает `ValueError`, если ключа ещё нет (частый случай — первая
        # правка после рестарта Redis).
        cache.set(key, self._version() + 1, None)

    def list(self, request, *args, **kwargs):
        # Язык — часть ключа: имена справочников переводятся, и ответ на `Accept-Language: en`
        # не должен подменять русский (раньше это делал `vary_on_headers`).
        key = f"lookup:{self._model_label}:{self._version()}:{get_language()}"
        payload = cache.get(key)
        if payload is None:
            payload = super().list(request, *args, **kwargs).data
            cache.set(key, payload, LOOKUP_CACHE_TTL)
        return Response(payload)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._bump_version()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._bump_version()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        self._bump_version()


class _ActiveOnlyListMixin:
    """Selection dropdowns must show only ACTIVE lookups, so deactivating a row in
    admin hides it everywhere (consistent with how services query the справочник,
    e.g. AI unit validation filters is_active=True). Applied to `list` only — so the
    response is identical for every caller (the list is cached by `_CachedLookupListMixin`
    and does NOT vary on auth) while retrieve/update/destroy keep the full queryset so an
    admin can still manage (and reactivate) an inactive row by id."""

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "action", None) == "list":
            qs = qs.filter(is_active=True)
        return qs


@extend_schema_view(
    list=extend_schema(summary="List countries", tags=["Master Data"]),
    create=extend_schema(summary="Create country", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get country", tags=["Master Data"]),
    update=extend_schema(summary="Update country", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update country", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete country", tags=["Master Data"]),
)
class CountryViewSet(_CachedLookupListMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for countries (read: public; write: admin)."""

    queryset = Country.objects.all().order_by("sort_order", "name")
    serializer_class = CountrySerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None
    operator_permission = "platform.settings"

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List currencies", tags=["Master Data"]),
    create=extend_schema(summary="Create currency", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get currency", tags=["Master Data"]),
    update=extend_schema(summary="Update currency", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update currency", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete currency", tags=["Master Data"]),
)
class CurrencyViewSet(_CachedLookupListMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for currencies (read: public; write: admin)."""

    queryset = Currency.objects.all().order_by("sort_order", "code")
    serializer_class = CurrencySerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None
    operator_permission = "platform.settings"

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List units of measure", tags=["Master Data"]),
    create=extend_schema(summary="Create unit", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get unit of measure", tags=["Master Data"]),
    update=extend_schema(summary="Update unit", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update unit", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete unit", tags=["Master Data"]),
)
class UnitOfMeasureViewSet(_CachedLookupListMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for units of measure (read: public; write: admin)."""

    queryset = UnitOfMeasure.objects.all().order_by("sort_order", "code")
    serializer_class = UnitOfMeasureSerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None
    operator_permission = "platform.settings"

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List delivery basis", tags=["Master Data"]),
    create=extend_schema(summary="Create delivery basis", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get delivery basis", tags=["Master Data"]),
    update=extend_schema(summary="Update delivery basis", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update delivery basis", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete delivery basis", tags=["Master Data"]),
)
class DeliveryBasisViewSet(_CachedLookupListMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for delivery basis terms (Incoterms). Read: public; write: admin."""

    queryset = DeliveryBasis.objects.all().order_by("sort_order", "code")
    serializer_class = DeliveryBasisSerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None
    operator_permission = "platform.settings"

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema(
    summary="Таможенные платежи по коду ТН ВЭД (витрина интегрированного тарифа ГТК)",
    description=(
        "Ставки сбора/пошлины/акциза/НДС и разрешительные документы по коду и стране "
        "происхождения. Данные НЕ хранятся у нас: запрос к tarif.customs.uz с суточным "
        "кэшем. 503 HS_DUTIES_UNAVAILABLE — источник недоступен, интерфейс показывает "
        "ссылку на калькулятор ГТК."
    ),
    tags=["Master Data"],
    parameters=[
        OpenApiParameter("origin", str, description="Код страны происхождения (ISO alpha-2, напр. CN)"),
    ],
    responses={200: OpenApiResponse(description="{payments, permits, fetched_at, source_url}")},
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def hs_code_duties(request, code: str):
    """Платежи по коду ТН ВЭД — тонкая обёртка над `customs_duties.get_duties` (Rule 8).

    Код проверяем ПО СВОЕМУ справочнику: гонять произвольные цифры в чужой сервис незачем,
    а «код есть в тарифе, но не в классификаторе» — сигнал, что справочник пора синхронизировать.
    """
    from .customs_duties import DutiesUnavailable, get_duties

    digits = "".join(char for char in (code or "") if char.isdigit())
    hs_code = HSCode.objects.filter(code=digits).first()
    if not hs_code:
        return Response({"detail": "HS_CODE_UNKNOWN"}, status=status.HTTP_404_NOT_FOUND)

    origin = (request.query_params.get("origin") or "").strip().upper()
    country = Country.objects.filter(code=origin).first() if origin else None
    if not country or not country.iso_numeric:
        # Страна происхождения определяет преференции — без неё ставка бессмысленна.
        # Пустой iso_numeric = запись завёл оператор вручную, тарифу её не скормить.
        return Response({"detail": "ORIGIN_COUNTRY_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        duties = get_duties(hs_code.code, country.iso_numeric)
    except DutiesUnavailable:
        return Response({"detail": "HS_DUTIES_UNAVAILABLE"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({**duties, "hs_code": hs_code.code, "hs_name": hs_code.name, "origin": country.code})
