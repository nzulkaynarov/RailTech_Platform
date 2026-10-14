from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from ..filters import StableOrderingFilter
from ..models import Product, ProductDocument, ProductImage
from ..serializers import ProductDocumentSerializer, ProductImageSerializer, ProductListSerializer, ProductSerializer


def catalog_ai_gate(user):
    """403, если у пользователя нет права роли `catalog.manage` в компании-продавце; None — путь открыт.

    ИИ по карточкам каталога (обогащение, подбор кода ТН ВЭД) — инструмент того, кто ведёт
    каталог. До M1-ERP-02 (волна 2) здесь стоял платный гейт `ai.enrich` (подписка/entitlement);
    монетизация удалена — решают права роли. Администратор (`is_superuser`) проходит всегда;
    дневной предохранитель расхода ИИ действует дальше в `enqueue_ai_job`.
    """
    if getattr(user, "is_superuser", False):
        return None
    from accounts.constants import Permission
    from accounts.services import member_has_permission, primary_seller_company_id

    seller_company_id = primary_seller_company_id(user)
    if not (seller_company_id and member_has_permission(user, seller_company_id, Permission.CATALOG_MANAGE)):
        return Response({"detail": "ROLE_NOT_PERMITTED"}, status=status.HTTP_403_FORBIDDEN)
    return None


@extend_schema_view(
    list=extend_schema(
        summary="List products",
        description=(
            "Returns products from the PIM catalog. Non-admin users only see PUBLISHED products. "
            "Filterable by domain_type, category, manufacturer, stock_status. "
            "Searchable by name, GOST/drawing, SKU. Server-side ordering via `?ordering=` "
            "(name, sku, demand_count, last_requested_at, created_at, updated_at; prefix with "
            "`-` for descending). `?ordering=` overrides the legacy `?order=demand` default."
        ),
        parameters=[
            OpenApiParameter(
                name="stock_status",
                description="Filter by supplier offer stock status code (e.g. IN_STOCK, ON_ORDER)",
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
        tags=["Catalog"],
    ),
    create=extend_schema(summary="Create product", description="Admin only.", tags=["Catalog"]),
    retrieve=extend_schema(
        summary="Get product details",
        description="Returns full product details including offers, images, and documents.",
        tags=["Catalog"],
    ),
    update=extend_schema(summary="Update product", description="Admin only.", tags=["Catalog"]),
    partial_update=extend_schema(summary="Partially update product", tags=["Catalog"]),
    destroy=extend_schema(summary="Delete product", tags=["Catalog"]),
)
class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD for PIM products.

    Public read access (PUBLISHED only for non-admin);
    write operations require Admin role.

    NOT page-cached (ARCH-02): the list serializer redacts cost/margin PER VIEWER
    (catalog _CostGateMixin), so a response is viewer-specific and must never be
    shared; the old cache_page keyed on the rotating Authorization JWT gave a ~0%
    hit rate + per-token cache bloat anyway.

    N+1 (fixed in R1 — until then this docstring claimed a freedom the code lacked):
    the list branch prefetches EVERY relation the row serializer touches and batches the
    reference-table probes behind `completeness` once per page via `CompletenessContext`,
    so the query count is flat in page_size (guarded by tests/test_r1_list_contract.py).
    """

    serializer_class = ProductSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer

    def get_queryset(self):
        user = self.request.user
        base = Product.objects.all().select_related(
            "category", "owner_company", "domain_type", "status", "uom", "brand", "brand__country"
        )
        if self.action == "list":
            queryset = base.prefetch_related(
                "images",
                "offers__stock_status",
                # R1: связь читает КАЖДАЯ строка списка — `offers__currency` для валюты
                # цены (`base_price_currency`).
                # Без prefetch это было бы по запросу на строку, то есть N+1 на всю страницу.
                "offers__currency",
            )
        else:
            queryset = base.prefetch_related(
                "images",
                "documents",
                "offers__stock_status",
                "offers__supplier",
                "offers__currency",
                "offers__delivery_basis",
            )
        # Non-admins see PUBLISHED + products manufactured by their own company
        if not (user.is_authenticated and user.is_superuser):
            from django.db.models import Q

            if user.is_authenticated:
                own_company_ids = user.memberships.filter(
                    is_active=True,
                ).values_list("company_id", flat=True)
                queryset = queryset.filter(
                    Q(status__code="PUBLISHED") | Q(owner_company_id__in=list(own_company_ids)),
                )
            else:
                queryset = queryset.filter(status__code="PUBLISHED")

        # Очередь наполнения продавца: только СВОИ карточки, отсортированные по спросу —
        # сначала то, что спрашивают чаще (эталон Ariba enablement: заниматься тем, что окупится
        # быстрее). Без этого «Номенклатура» продавца оставалась витриной чужого каталога.
        if self.request.query_params.get("mine") in ("1", "true", "True"):
            if not user.is_authenticated:
                queryset = queryset.none()
            else:
                own_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
                queryset = queryset.filter(owner_company_id__in=own_ids)
        status_code = self.request.query_params.get("status")
        if status_code:
            queryset = queryset.filter(status__code=status_code)
        # Происхождение карточки — питает табы единого реестра (аудит §5.2): «Кандидаты из
        # заявок» (`?origin=rfq` — карточка родилась из строки КП/заявки: есть спрос или
        # заявка-источник) vs «Черновики» (`?origin=manual` — заведена руками). Иные значения
        # молча игнорируются.
        origin = self.request.query_params.get("origin")
        if origin in ("rfq", "manual"):
            from django.db.models import Q

            came_from_rfq = Q(demand_count__gt=0) | Q(source_deal__isnull=False)
            queryset = queryset.filter(came_from_rfq) if origin == "rfq" else queryset.exclude(came_from_rfq)
        # Легаси-порядок очереди наполнения (`catalogApi.getMyCandidates` шлёт `?order=demand`).
        # Приоритет СОЗНАТЕЛЬНО отдан явному `?ordering=`: `OrderingFilter` работает позже
        # `get_queryset()` и его `order_by` перекрывает эту ветку. `?order=demand` остаётся
        # умолчанием очереди, `?ordering=` — осознанным выбором пользователя, и выбор человека
        # сильнее умолчания.
        if self.request.query_params.get("order") == "demand":
            queryset = queryset.order_by("-demand_count", "-last_requested_at", "name")
        # Worklist переклассификации (SAP GTS): карточки, чей код ТН ВЭД выведен из редакции
        # автосинком. Без него карточка тихо наследовала бы мёртвый код в каждое новое КП.
        if self.request.query_params.get("needs_reclassification") in ("1", "true", "True"):
            from catalog.hs_suggest import cards_with_retired_codes

            queryset = queryset.filter(pk__in=cards_with_retired_codes().values_list("pk", flat=True))

        # Filter by stock_status (from supplier offers)
        stock_status = self.request.query_params.get("stock_status")
        if stock_status:
            queryset = queryset.filter(offers__stock_status__code=stock_status).distinct()

        return queryset

    # `StableOrderingFilter` — ПОСЛЕДНИЙ: его `order_by` обязан перекрывать порядок, заданный
    # в `get_queryset()` (легаси `?order=demand`), а не наоборот.
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, StableOrderingFilter]
    filterset_fields = {
        "domain_type__code": ["exact"],
        "category": ["exact"],
        "brand": ["exact"],
    }
    #: Белый список сортировок. До R1 `?ordering=` молча не работал вовсе: бэкенд не подключал
    #: `OrderingFilter`, и клик по заголовку колонки ничего не менял. Поле вне списка DRF
    #: игнорирует (порядок остаётся прежним) — сортировка по произвольному столбцу была бы
    #: дырой: `?ordering=offers__base_price` раскрыл бы закрытую костгейтом цену перестановкой.
    ordering_fields = ["name", "sku", "demand_count", "last_requested_at", "created_at", "updated_at"]
    search_fields = ["name", "gost_drawing", "sku"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        # Публикует ВЛАДЕЛЕЦ карточки (Amazon/Alibaba/Shopify), а порог качества держит
        # детерминированная полнота — см. `catalog/publishing.py`. Право платформы сохраняется.
        if self.action in (
            "publish",
            "bulk_publish",
            "unpublish",
            "archive",
            "restore",
            "bulk_archive",
            "coverage",
            "merge",
            "hs_suggest",
            "hs_validate",
            "hs_browse",
            "hs_lookup",
        ):
            return [permissions.IsAuthenticated()]
        from core.permissions import IsProductManagerOrAdmin

        return [permissions.IsAuthenticated(), IsProductManagerOrAdmin()]

    def perform_update(self, serializer):
        # T2: смена кода ТН ВЭД оставляет след с источником (manual — правка из формы).
        old_code = serializer.instance.hs_code or ""
        product = serializer.save()
        from catalog.services import log_hs_code_change

        log_hs_code_change(product, old_code, self.request.user, origin="manual")

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_superuser:
            # N3 (дыра №4 аудита): карточка БЕЗ owner_company — ничья, продавец никогда не
            # сможет взять её в работу (can_manage вечно False). Оператор обязан назвать
            # компанию-владельца (SAP: материал всегда в орг-области).
            from rest_framework.exceptions import ValidationError

            from accounts.models import Company

            owner_id = self.request.data.get("owner_company")
            owner = Company.objects.filter(pk=owner_id).first() if owner_id else None
            if owner is None:
                raise ValidationError({"detail": "OWNER_COMPANY_REQUIRED"})
            serializer.save(owner_company=owner)
            return
        from accounts.constants import Permission
        from accounts.services.permissions import member_has_permission

        seller_membership = next(
            (
                membership
                for membership in user.memberships.filter(is_active=True).in_seller_company().select_related("company")
                # N3: карточка приписывается компании, где у автора ЕСТЬ catalog.manage, —
                # первое попавшееся членство могло быть компанией без такого права.
                if member_has_permission(user, membership.company_id, Permission.CATALOG_MANAGE)
            ),
            None,
        )
        if not seller_membership:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("NO_SELLER_MEMBERSHIP")
        serializer.save(owner_company=seller_membership.company)

    @extend_schema(
        summary="Suggest HS (ТН ВЭД) codes for a product name",
        description=(
            "Кандидаты кода ТН ВЭД из СПРАВОЧНИКА (`master_data.HSCode`) по наименованию или "
            "введённым цифрам. Не генерирует код: придуманный ТН ВЭД хуже отсутствующего — "
            "продавец узнал бы об ошибке на границе. Пустой справочник → пустой ответ."
        ),
        parameters=[OpenApiParameter(name="q", type=str, location=OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiResponse(description="[{code, name, level, score}]")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="hs-suggest", permission_classes=[permissions.IsAuthenticated])
    def hs_suggest(self, request):
        from catalog.hs_suggest import suggest_hs_codes

        return Response({"candidates": suggest_hs_codes(request.query_params.get("q", ""), limit=8)})

    @extend_schema(
        summary="Browse the HS classifier tree",
        description="Дети узла дерева ТН ВЭД. Без parent — корневые группы (2 знака).",
        parameters=[OpenApiParameter(name="parent", type=str, location=OpenApiParameter.QUERY, required=False)],
        responses={200: OpenApiResponse(description="{children: [{code,name,level,has_children}]}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="hs-browse", permission_classes=[permissions.IsAuthenticated])
    def hs_browse(self, request):
        from django.db.models import Count
        from django.db.models import Q as DQ
        from django.utils import timezone

        from master_data.models import HSCode

        today = timezone.localdate()
        parent = "".join(ch for ch in request.query_params.get("parent", "") if ch.isdigit())
        base = HSCode.objects.exclude(valid_until__lt=today)
        rows = base.filter(parent__code=parent) if parent else base.filter(level=2)
        children = list(
            rows.annotate(child_count=Count("children", filter=DQ(children__valid_until__isnull=True)))
            .order_by("code")
            .values("code", "name", "level", "child_count")[:500]
        )
        return Response(
            {
                "children": [
                    {"code": r["code"], "name": r["name"], "level": r["level"], "has_children": r["child_count"] > 0}
                    for r in children
                ]
            }
        )

    @extend_schema(
        summary="Bulk classify HS codes (202, suggestions only)",
        description=(
            "Пакетный подбор кодов ТН ВЭД для СВОИХ карточек. Возвращает ПРЕДЛОЖЕНИЯ — карточки "
            "меняются только через hs-apply после подтверждения человеком (Avalara-паттерн)."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {"product_ids": {"type": "array", "items": {"type": "integer"}}},
            }
        },
        responses={202: OpenApiResponse(description="{task_id}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"], url_path="hs-classify", permission_classes=[permissions.IsAuthenticated])
    def hs_classify(self, request):
        from catalog.publishing import can_manage
        from sourcing.ai_jobs import enqueue_ai_job

        gate = catalog_ai_gate(request.user)
        if gate is not None:
            return gate
        ids = [int(pk) for pk in (request.data.get("product_ids") or []) if str(pk).isdigit()][:100]
        if not ids:
            return Response({"detail": "PRODUCT_IDS_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        # Только свои карточки: чужие молча выбрасываются ДО постановки платной задачи.
        own = [p.pk for p in Product.objects.filter(pk__in=ids) if can_manage(request.user, p)]
        if not own:
            return Response({"detail": "PRODUCT_NOT_YOURS"}, status=status.HTTP_403_FORBIDDEN)
        return enqueue_ai_job("hs_classify", {"product_ids": own}, request.user)

    @extend_schema(
        summary="Apply confirmed HS codes to products",
        description="Применить ПОДТВЕРЖДЁННЫЕ человеком коды: [{product_id, code}]. Код обязан быть в справочнике.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "assignments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"product_id": {"type": "integer"}, "code": {"type": "string"}},
                        },
                    }
                },
            }
        },
        responses={200: OpenApiResponse(description="{applied, skipped}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"], url_path="hs-apply", permission_classes=[permissions.IsAuthenticated])
    def hs_apply(self, request):
        from catalog.hs_suggest import is_known_code
        from catalog.publishing import can_manage
        from catalog.services import log_hs_code_change

        applied, skipped = [], []
        for row in (request.data.get("assignments") or [])[:100]:
            product = Product.objects.filter(pk=row.get("product_id")).first()
            code = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())
            if product is None or not code or not can_manage(request.user, product):
                skipped.append({"product_id": row.get("product_id"), "reason": "PRODUCT_NOT_YOURS"})
                continue
            if not is_known_code(code):
                skipped.append({"product_id": product.pk, "reason": "HS_CODE_UNKNOWN"})
                continue
            old = product.hs_code or ""
            product.hs_code = code
            product.save(update_fields=["hs_code", "updated_at"])
            log_hs_code_change(product, old, request.user, origin="ai")
            applied.append(product.pk)
        return Response({"applied": applied, "skipped": skipped})

    @extend_schema(
        summary="AI lookup: describe the product in your own words (202)",
        description=(
            "ИИ-режим справочника: свободное описание → код из классификатора с объяснением. "
            "ARCH-01: 202 {task_id}, результат по sourcing/ai-status/."
        ),
        request={"application/json": {"type": "object", "properties": {"description": {"type": "string"}}}},
        responses={202: OpenApiResponse(description="{task_id}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"], url_path="hs-lookup", permission_classes=[permissions.IsAuthenticated])
    def hs_lookup(self, request):
        from sourcing.ai_jobs import enqueue_ai_job

        gate = catalog_ai_gate(request.user)
        if gate is not None:
            return gate
        description = (request.data.get("description") or "").strip()
        if not description:
            return Response({"detail": "DESCRIPTION_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        return enqueue_ai_job("hs_lookup", {"description": description[:500]}, request.user)

    @extend_schema(
        summary="Validate an HS (ТН ВЭД) code softly",
        description=(
            "Статус кода для мягкой валидации поля: known/active/name. НИЧЕГО не блокирует — "
            "интерфейс лишь подсвечивает «нет в справочнике» или «выведен из редакции»."
        ),
        parameters=[OpenApiParameter(name="code", type=str, location=OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiResponse(description="{known, active, name}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="hs-validate", permission_classes=[permissions.IsAuthenticated])
    def hs_validate(self, request):
        from catalog.hs_suggest import validate_hs_code

        return Response(validate_hs_code(request.query_params.get("code", "")))

    @extend_schema(
        summary="Merge a duplicate product card into this one",
        description=(
            "Сливает карточку-дубль в текущую: пустые поля дозаполняются, спрос суммируется, "
            "офферы и строки КП переезжают, дубль уходит в АРХИВ (не удаляется — на него "
            "могут ссылаться исторические документы)."
        ),
        request={"application/json": {"type": "object", "properties": {"duplicate_id": {"type": "integer"}}}},
        responses={200: OpenApiResponse(description="Merged"), 400: OpenApiResponse(description="Cannot merge")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def merge(self, request, pk=None):
        from catalog.merging import merge_products

        survivor = self.get_object()
        duplicate_id = request.data.get("duplicate_id")
        if not duplicate_id:
            return Response({"detail": "DUPLICATE_ID_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        duplicate = Product.objects.filter(pk=duplicate_id).first()
        if duplicate is None:
            return Response({"detail": "PRODUCT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        merged, error = merge_products(survivor, duplicate, request.user)
        if error:
            code = 403 if error in ("PRODUCT_NOT_YOURS", "MERGE_CROSS_COMPANY_FORBIDDEN") else 400
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(merged).data)

    @extend_schema(
        summary="Duplicate-card suggestions for the caller's own catalog",
        description=(
            "Группы вероятных дублей СВОИХ карточек по точным ключам (бренд+артикул, ГОСТ, "
            "точное имя). Система предлагает — человек решает (Akeneo/Salesforce dedupe)."
        ),
        responses={200: OpenApiResponse(description="[{survivor, duplicates}]")},
        tags=["Catalog"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="duplicate-suggestions",
        permission_classes=[permissions.IsAuthenticated],
    )
    def duplicate_suggestions(self, request):
        from catalog.merging import duplicate_suggestions

        membership = (
            request.user.memberships.filter(is_active=True).in_seller_company().select_related("company").first()
        )
        if membership is None:
            return Response({"detail": "NO_SELLER_MEMBERSHIP"}, status=status.HTTP_403_FORBIDDEN)
        return Response({"groups": duplicate_suggestions(membership.company)})

    @extend_schema(
        summary="Catalog coverage metric",
        description=(
            "Доля строк КП, опирающихся на карточку товара — одна цифра, показывающая, работает "
            "ли направление «Номенклатура». Продавец видит свой срез, платформа — общий."
        ),
        responses={200: OpenApiResponse(description="{lines_total, lines_with_product, percent, candidates_pending}")},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def coverage(self, request):
        from catalog.coverage import catalog_coverage

        user = request.user
        seller = None
        if not user.is_superuser:
            membership = user.memberships.filter(is_active=True).in_seller_company().select_related("company").first()
            if membership is None:
                return Response({"detail": "NO_SELLER_MEMBERSHIP"}, status=status.HTTP_403_FORBIDDEN)
            seller = membership.company
        return Response(catalog_coverage(seller))

    @extend_schema(
        summary="Publish a product (owner)",
        description=(
            "Публикует карточку. Доступно ВЛАДЕЛЬЦУ и платформе. Требует полноты: неполная "
            "карточка отвечает `PRODUCT_INCOMPLETE:<коды недостающих полей>`."
        ),
        responses={200: OpenApiResponse(description="Published"), 400: OpenApiResponse(description="Incomplete")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        from catalog.publishing import publish_product

        product = self.get_object()
        published, error = publish_product(product, request.user)
        if error:
            code = 403 if error == "PRODUCT_NOT_YOURS" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(published).data)

    @extend_schema(
        summary="Bulk publish products",
        description=(
            "Publish multiple products at once by providing a list of product IDs. "
            "Maximum 500 products per batch. Доступно владельцу карточек и платформе."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "product_ids": {"type": "array", "items": {"type": "integer"}},
                },
            }
        },
        responses={
            200: OpenApiResponse(description="Products published successfully"),
            400: OpenApiResponse(description="Invalid IDs or batch too large"),
        },
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"])
    def bulk_publish(self, request):
        product_ids = request.data.get("product_ids", [])
        if not product_ids:
            return Response(
                {"detail": "PRODUCT_IDS_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(product_ids, list):
            return Response(
                {"detail": "product_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product_ids = [int(pid) for pid in product_ids]
        except (ValueError, TypeError):
            return Response(
                {"detail": "product_ids must contain valid integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(product_ids) > 500:
            return Response(
                {"detail": "BATCH_TOO_LARGE"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Пакет отчитывается ПОСТРОЧНО: частичный успех честнее отказа всей пачки (Akeneo,
        # Shopify делают так же). Каждая карточка проходит те же владение и полноту, что и
        # одиночная публикация.
        from catalog.publishing import publish_many

        report = publish_many(product_ids, request.user)
        if not report["published"] and report["skipped"]:
            return Response({"detail": report["skipped"][0]["error"], **report}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"message": f"Successfully published {len(report['published'])} products.", **report},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Unpublish a product (owner)",
        description=(
            "Снимает карточку с витрины: PUBLISHED → DRAFT (Shopify: Active → Draft двусторонне). "
            "Право то же, что у публикации."
        ),
        responses={200: OpenApiResponse(description="Unpublished"), 400: OpenApiResponse(description="Not published")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        from catalog.publishing import unpublish_product

        product = self.get_object()
        unpublished, error = unpublish_product(product, request.user)
        if error:
            code = 403 if error == "PRODUCT_NOT_YOURS" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(unpublished).data)

    @extend_schema(
        summary="Archive a product (owner)",
        description=(
            "Убирает карточку в архив (обратимо — см. restore). Отдельное действие от снятия "
            "с публикации: Draft — «ещё готовится», Archive — «больше не работаем» (Shopify)."
        ),
        responses={200: OpenApiResponse(description="Archived"), 400: OpenApiResponse(description="Already archived")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        from catalog.publishing import archive_product

        product = self.get_object()
        archived, error = archive_product(product, request.user)
        if error:
            code = 403 if error == "PRODUCT_NOT_YOURS" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(archived).data)

    @extend_schema(
        summary="Restore a product from the archive",
        description=(
            "Возвращает карточку из архива в черновики (ARCHIVED → DRAFT). Витрину карточка "
            "заслуживает заново через publish. Закрывает «архив — чёрную дыру» слитых дублей."
        ),
        responses={200: OpenApiResponse(description="Restored"), 400: OpenApiResponse(description="Not archived")},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        from catalog.publishing import restore_product

        product = self.get_object()
        restored, error = restore_product(product, request.user)
        if error:
            code = 403 if error == "PRODUCT_NOT_YOURS" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(self.get_serializer(restored).data)

    @extend_schema(
        summary="Bulk archive products",
        description=(
            "Archive multiple products at once. Maximum 500 products per batch. "
            "Отчёт построчный: {archived: [...], skipped: [{product_id, error}]}."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "product_ids": {"type": "array", "items": {"type": "integer"}},
                },
            }
        },
        responses={
            200: OpenApiResponse(description="Products archived (line-by-line report)"),
            400: OpenApiResponse(description="Invalid IDs or batch too large"),
        },
        tags=["Catalog"],
    )
    @action(detail=False, methods=["post"])
    def bulk_archive(self, request):
        product_ids = request.data.get("product_ids", [])
        if not product_ids:
            return Response({"detail": "PRODUCT_IDS_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(product_ids, list):
            return Response({"detail": "product_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            product_ids = [int(pid) for pid in product_ids]
        except (ValueError, TypeError):
            return Response({"detail": "product_ids must contain valid integers"}, status=status.HTTP_400_BAD_REQUEST)
        if len(product_ids) > 500:
            return Response({"detail": "BATCH_TOO_LARGE"}, status=status.HTTP_400_BAD_REQUEST)

        # Построчный отчёт — тот же контракт частичного успеха, что у bulk_publish.
        from catalog.publishing import archive_many

        report = archive_many(product_ids, request.user)
        if not report["archived"] and report["skipped"]:
            return Response({"detail": report["skipped"][0]["error"], **report}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"message": f"Successfully archived {len(report['archived'])} products.", **report},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Download import template",
        description="Generate and download an XLSX template for bulk catalog import.",
        responses={
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiResponse(
                description="XLSX template file"
            ),
        },
        tags=["Catalog"],
    )
    @extend_schema(
        summary="Export products list",
        description="Export filtered product list as CSV or XLSX.",
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="products",
            columns=[
                ("id", "ID", lambda p: p.id),
                ("sku", "SKU", lambda p: p.sku or ""),
                ("name", "Name", lambda p: p.name),
                ("domain_type", "Domain", lambda p: p.domain_type.code if p.domain_type_id else ""),
                ("category", "Category", lambda p: p.category.name if p.category_id else ""),
                ("status", "Status", lambda p: p.status.code if p.status_id else ""),
                ("brand", "Brand", lambda p: p.brand.name if p.brand_id else ""),
                ("created_at", "Created", lambda p: p.created_at.isoformat() if p.created_at else ""),
            ],
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export-template",
        permission_classes=[permissions.IsAuthenticated],
    )
    def export_template(self, request):
        """Generate an XLSX template for catalog import."""
        import openpyxl
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Products"
        # Column names align with ProductResource (M9/M10) and the import-engine
        # aliases (sourcing/catalog_import.py) so an export round-trips back through
        # import without losing the MPN dedup key or the HS/customs code.
        headers = [
            "name",
            "sku",
            "description",
            "domain_type",
            "category",
            "uom",
            "brand",
            "manufacturer_part_number",
            "gost_drawing",
            "hs_code",
        ]
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20

        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="railtech_import_template.xlsx"'
        wb.save(response)
        return response

    @extend_schema(
        summary="Upload product image",
        description="Attach an image file to a product. Multipart upload.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "format": "binary"},
                    "is_main": {"type": "boolean", "default": False},
                    "alt_text": {"type": "string"},
                },
            }
        },
        responses={201: ProductImageSerializer},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-image",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_image(self, request, pk=None):
        product = self.get_object()
        image_file = request.FILES.get("image")
        if not image_file:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_image_upload

        try:
            validate_image_upload(image_file)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        is_main = str(request.data.get("is_main", "false")).lower() in ("true", "1")
        alt_text = request.data.get("alt_text", "")

        if is_main:
            ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)

        img = ProductImage.objects.create(
            product=product,
            image=image_file,
            is_main=is_main,
            alt_text=alt_text,
        )
        return Response(ProductImageSerializer(img).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete product image",
        responses={204: None, 404: OpenApiResponse(description="Image not found")},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="delete-image/(?P<image_id>[0-9]+)",
        url_name="delete-image",
    )
    def delete_image(self, request, pk=None, image_id=None):
        product = self.get_object()
        img = ProductImage.objects.filter(pk=image_id, product=product).first()
        if not img:
            return Response({"detail": "IMAGE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if img.image:
            img.image.delete(save=False)
        img.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Upload product document",
        description="Attach a technical document (PDF, DOCX) to a product.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "name": {"type": "string"},
                },
            }
        },
        responses={201: ProductDocumentSerializer},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-document",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_document(self, request, pk=None):
        product = self.get_object()
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_document_upload

        try:
            validate_document_upload(file_obj)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        name = request.data.get("name") or file_obj.name
        doc = ProductDocument.objects.create(product=product, file=file_obj, name=name)
        return Response(ProductDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete product document",
        responses={204: None, 404: OpenApiResponse(description="Document not found")},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="delete-document/(?P<doc_id>[0-9]+)",
        url_name="delete-document",
    )
    def delete_document(self, request, pk=None, doc_id=None):
        product = self.get_object()
        doc = ProductDocument.objects.filter(pk=doc_id, product=product).first()
        if not doc:
            return Response({"detail": "DOCUMENT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
