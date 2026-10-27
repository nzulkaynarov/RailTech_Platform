from django.core.cache import cache
from django.db.models import ProtectedError
from django.utils.translation import get_language
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.audit import AuditedWriteMixin
from core.permissions import HasRolePermission, RoleGatedViewMixin

from .models import Country, Currency, DeliveryBasis, HSCode, UnitOfMeasure
from .serializers import CountrySerializer, CurrencySerializer, DeliveryBasisSerializer, UnitOfMeasureSerializer


def _lookup_write_permissions(view):
    """Чтение справочника — публичное, ЗАПИСЬ — по праву `settings.edit` (или администратор)."""
    if getattr(view, "action", None) in ("list", "retrieve"):
        return [permissions.AllowAny()]
    return [permissions.IsAuthenticated(), HasRolePermission()]


LOOKUP_CACHE_TTL = 60 * 10  # 10 min — справочники меняются редко

# Описание контракта (D2-0): параметр выборки и отказ удаления одинаковы у четырёх справочников.
_INCLUDE_INACTIVE = [
    OpenApiParameter(
        "include_inactive",
        str,
        OpenApiParameter.QUERY,
        description="`1`/`true` — вместе с отключёнными строками; только для держателя `settings.edit` или администратора",
    )
]
_IN_USE = OpenApiResponse(description="LOOKUP_IN_USE[:Модели,…] — на строку ссылаются данные; отключите её вместо удаления")


def _lookup_snapshot(instance) -> dict:
    """Что записываем в след: только опорные поля справочника, без служебных."""
    # Поля объявлены в `AbstractLookup`, миксин надет только на его наследников — защитный
    # `hasattr` был всегда истинен и лишь маскировал бы ошибку «надели не на тот класс».
    return {field: str(getattr(instance, field)) for field in ("code", "name", "sort_order", "is_active")}


class _CachedLookupListMixin(AuditedWriteMixin):
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
        # Формат ключа задан в `master_data/signals.py` — здесь только ЧТЕНИЕ. Сброс держит
        # сигнал на записи модели: он ловит и вьюсет, и админку, и management-команду, и шелл.
        from .signals import lookup_version_key

        return cache.get(lookup_version_key(self.queryset.model), 1)

    def list(self, request, *args, **kwargs):
        # Язык — часть ключа: имена справочников переводятся, и ответ на `Accept-Language: en`
        # не должен подменять русский (раньше это делал `vary_on_headers`).
        # Признак выборки — часть ключа: иначе привилегированный ответ с отключёнными
        # строками осел бы в общем кэше и уехал всем арендаторам, включая анонимных.
        scope = "all" if getattr(self, "_wants_inactive", lambda: False)() else "active"
        key = f"lookup:{self._model_label}:{self._version()}:{get_language()}:{scope}"
        payload = cache.get(key)
        if payload is None:
            payload = super().list(request, *args, **kwargs).data
            cache.set(key, payload, LOOKUP_CACHE_TTL)
        return Response(payload)

    #: Строки этих справочников печатаются в документах ВСЕХ арендаторов: валюта в КП, единица
    #: у позиции, базис поставки в договоре, страна в реквизитах. Правил их оператор платформы,
    #: а в «Журнале доступа» не было ни одной записи (замер 26-08: `admin.lookup*` — ноль строк).
    audit_event_prefix = "lookup"

    def audit_action(self, instance, event: str) -> str:
        return f"Справочник {event}: {getattr(instance, 'code', instance.pk)}"

    def audit_snapshot(self, instance):
        return _lookup_snapshot(instance)

    def audit_event_params(self, instance) -> dict:
        return {"model": instance._meta.label_lower, "code": str(getattr(instance, "code", ""))}


class _GuardedDestroyMixin:
    """Удаление строки, на которую ссылаются данные арендаторов, — внятный отказ, не 500.

    Ссылки объявлены с `on_delete=PROTECT` (единица у товара, валюта у КП, страна у компании,
    базис поставки у сделки), поэтому БД такое удаление и так не пропускала — терялась только
    внятность: DRF отдавал `ProtectedError` наружу как 500 с HTML-страницей. Оператор видел
    «Не удалось удалить» и повторял попытку, потому что причина не названа.

    Эталон — Odoo Archive: запись, на которую ссылаются, удалить нельзя, из оборота её выводят
    архивированием (у нас — `is_active=False`). Тот же приём уже применён в проекте к шаблонам
    документов (`TEMPLATE_IN_USE`, волна F3) — здесь он один на все ЧЕТЫРЕ справочника, потому
    что точечная починка одной вкладки оставила бы три таких же пятисотки.
    """

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            # Называем, ЧТО держит строку — модели, а не сами записи: перечислять чужие строки
            # арендаторов оператору незачем. Код в голове ответа, машинный суффикс после
            # двоеточия витрина отбрасывает при переводе (см. `frontend/src/lib/apiError.ts`).
            holders = sorted({obj._meta.verbose_name.title() for obj in exc.protected_objects})
            detail = "LOOKUP_IN_USE" + (":" + ",".join(holders) if holders else "")
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


class _ActiveOnlyListMixin:
    """Selection dropdowns must show only ACTIVE lookups, so deactivating a row in
    admin hides it everywhere (consistent with how services query the справочник,
    e.g. AI unit validation filters is_active=True). Applied to `list` only — so the
    response is identical for every caller (the list is cached by `_CachedLookupListMixin`
    and does NOT vary on auth) while retrieve/update/destroy keep the full queryset so an
    admin can still manage (and reactivate) an inactive row by id."""

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "action", None) == "list" and not self._wants_inactive():
            qs = qs.filter(is_active=True)
        return qs

    def _wants_inactive(self) -> bool:
        """`?include_inactive=1` — только для того, кто имеет право ПРАВИТЬ справочник.

        Отключённая строка исчезала из списка навсегда: включить её обратно через интерфейс
        было нельзя, хотя гасил её тот же оператор. Возвращать `objects.all()` всем НЕЛЬЗЯ —
        на общем списке висят выпадающие списки всех арендаторов и общий кэш, поэтому
        привилегированная выборка живёт под своим ключом кэша (см. `_CachedLookupListMixin`).
        """
        request = getattr(self, "request", None)
        if request is None or str(request.query_params.get("include_inactive", "")) not in ("1", "true", "True"):
            return False
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import is_seller, staff_has_permission

        return is_seller(user) and staff_has_permission(user, "settings.edit")


@extend_schema_view(
    list=extend_schema(summary="List countries", parameters=_INCLUDE_INACTIVE, tags=["Master Data"]),
    create=extend_schema(summary="Create country", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get country", tags=["Master Data"]),
    update=extend_schema(summary="Update country", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update country", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete country", responses={204: None, 400: _IN_USE}, tags=["Master Data"]),
)
class CountryViewSet(
    RoleGatedViewMixin, _CachedLookupListMixin, _GuardedDestroyMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet
):
    """CRUD for countries (read: public; write: admin)."""

    required_permissions = {
        "create": "settings.edit",
        "update": "settings.edit",
        "partial_update": "settings.edit",
        "destroy": "settings.edit",
    }

    queryset = Country.objects.all().order_by("sort_order", "name")
    serializer_class = CountrySerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List currencies", parameters=_INCLUDE_INACTIVE, tags=["Master Data"]),
    create=extend_schema(summary="Create currency", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get currency", tags=["Master Data"]),
    update=extend_schema(summary="Update currency", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update currency", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete currency", responses={204: None, 400: _IN_USE}, tags=["Master Data"]),
)
class CurrencyViewSet(
    RoleGatedViewMixin, _CachedLookupListMixin, _GuardedDestroyMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet
):
    """CRUD for currencies (read: public; write: admin)."""

    required_permissions = {
        "create": "settings.edit",
        "update": "settings.edit",
        "partial_update": "settings.edit",
        "destroy": "settings.edit",
    }

    queryset = Currency.objects.all().order_by("sort_order", "code")
    serializer_class = CurrencySerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List units of measure", parameters=_INCLUDE_INACTIVE, tags=["Master Data"]),
    create=extend_schema(summary="Create unit", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get unit of measure", tags=["Master Data"]),
    update=extend_schema(summary="Update unit", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update unit", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete unit", responses={204: None, 400: _IN_USE}, tags=["Master Data"]),
)
class UnitOfMeasureViewSet(
    RoleGatedViewMixin, _CachedLookupListMixin, _GuardedDestroyMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet
):
    """CRUD for units of measure (read: public; write: admin)."""

    required_permissions = {
        "create": "settings.edit",
        "update": "settings.edit",
        "partial_update": "settings.edit",
        "destroy": "settings.edit",
    }

    queryset = UnitOfMeasure.objects.all().order_by("sort_order", "code")
    serializer_class = UnitOfMeasureSerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None

    def get_permissions(self):
        return _lookup_write_permissions(self)


@extend_schema_view(
    list=extend_schema(summary="List delivery basis", parameters=_INCLUDE_INACTIVE, tags=["Master Data"]),
    create=extend_schema(summary="Create delivery basis", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get delivery basis", tags=["Master Data"]),
    update=extend_schema(summary="Update delivery basis", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update delivery basis", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete delivery basis", responses={204: None, 400: _IN_USE}, tags=["Master Data"]),
)
class DeliveryBasisViewSet(
    RoleGatedViewMixin, _CachedLookupListMixin, _GuardedDestroyMixin, _ActiveOnlyListMixin, viewsets.ModelViewSet
):
    """CRUD for delivery basis terms (Incoterms). Read: public; write: admin."""

    required_permissions = {
        "create": "settings.edit",
        "update": "settings.edit",
        "partial_update": "settings.edit",
        "destroy": "settings.edit",
    }

    queryset = DeliveryBasis.objects.all().order_by("sort_order", "code")
    serializer_class = DeliveryBasisSerializer
    # `permission_classes` здесь НЕ указан намеренно: его полностью перекрывает
    # `get_permissions` ниже. Оставленная строка врала бы читателю о реальном правиле доступа.
    pagination_class = None

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
