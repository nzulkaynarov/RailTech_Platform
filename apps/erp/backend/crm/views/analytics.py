from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


@extend_schema(
    summary="Dashboard analytics",
    description=(
        "Comprehensive dashboard KPIs: deals volume, active requests, "
        "catalog items, clients count, deals by month, activity by day, "
        "top products, counterparties breakdown, and request completion."
    ),
    parameters=[
        OpenApiParameter(
            name="period",
            description="Analytics period (7d, 30d, 90d). Default: 30d",
            type=str,
            location=OpenApiParameter.QUERY,
            enum=["7d", "30d", "90d"],
        ),
    ],
    responses={200: OpenApiResponse(description="Dashboard analytics data")},
    tags=["Analytics"],
)
class DashboardAnalyticsView(APIView):
    """Сводные KPI главного дашборда.
    GET /api/v1/crm/analytics/dashboard/?period=30d

    Тонкая обёртка (Rule 8) — как и три соседние вьюхи этого файла: разобрать параметр →
    ОДИН вызов сервиса → Response. Весь подсчёт, разрешение области видимости B2B и кэш
    живут в `crm.services.dashboard_analytics`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from crm.services.dashboard_analytics import DEFAULT_PERIOD, dashboard_analytics

        period = request.query_params.get("period", DEFAULT_PERIOD)
        return Response(dashboard_analytics(request.user, request, period))


@extend_schema(
    summary="Time-to-first-КП wedge metric",
    description=(
        "Hours from the request entering ERP → first КП sent, aggregated (median/avg/p90). Admin sees "
        "everything; own-company staff see the own company's КП. The headline wedge KPI."
    ),
    parameters=[
        OpenApiParameter(name="since_days", type=int, location=OpenApiParameter.QUERY, required=False),
    ],
    responses={200: OpenApiResponse(description="{sample_size, median_hours, avg_hours, p90_hours, ...}")},
    tags=["Analytics"],
)
class TimeToFirstQuoteView(APIView):
    """ADR-0006 Move 4 wedge metric. GET /api/v1/crm/analytics/time-to-first-quote/?since_days=30"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from accounts.services.permissions import seller_company_ids as own_seller_company_ids
        from crm.services.metrics import time_to_first_quote_stats

        is_staff = getattr(request.user, "is_superuser", False)
        # Administrator → everything (None). Own-company staff → the own company's КП. A buyer
        # account has no seller company → empty scope → zero sample.
        seller_company_ids = None if is_staff else own_seller_company_ids(request.user)
        try:
            since_days = int(request.query_params.get("since_days")) if request.query_params.get("since_days") else None
        except (TypeError, ValueError):
            since_days = None
        data = time_to_first_quote_stats(seller_company_ids=seller_company_ids, since_days=since_days)
        return Response(data)


@extend_schema(
    summary="Recent documents (dashboard widget)",
    description=(
        "The viewer's newest documents ACROSS types — КП / контракты / инвойсы / акты / "
        "сгенерированные — merged and sorted by date desc, capped at `limit`. Each type is "
        "company-scoped exactly like its own list endpoint: own-company staff see every document, "
        "a client account only its own company's (never another company's DRAFT)."
    ),
    parameters=[
        OpenApiParameter(
            name="limit",
            description="Number of documents to return (1..20, clamped). Default 8.",
            type=int,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: inline_serializer(
            "RecentDocumentsResponse",
            fields={
                "results": drf_serializers.ListField(
                    child=inline_serializer(
                        "RecentDocument",
                        fields={
                            "type": drf_serializers.ChoiceField(
                                choices=["quote", "contract", "invoice", "act", "generated"]
                            ),
                            "id": drf_serializers.IntegerField(),
                            "label": drf_serializers.CharField(),
                            "status_code": drf_serializers.CharField(allow_null=True),
                            "date": drf_serializers.DateTimeField(),
                            "deal": drf_serializers.IntegerField(allow_null=True),
                        },
                    )
                )
            },
        )
    },
    tags=["Analytics"],
)
class RecentDocumentsView(APIView):
    """«Недавние документы» feed for the dashboard station widget.
    GET /api/v1/crm/analytics/recent-documents/?limit=8

    Thin wrapper (Rule 8): resolve limit → ONE service call → return. All company-scoping
    (incl. the hidden-competition boundary) lives in crm.services.recent_documents.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from crm.services.recent_documents import recent_documents

        results = recent_documents(request.user, request, limit=request.query_params.get("limit"))
        return Response({"results": results})


@extend_schema(
    summary="Search documents (global document search)",
    description=(
        "Cross-type textual search over the viewer's documents — КП / контракты / инвойсы / акты / "
        "сгенерированные — matched case-insensitively by `q` on document number, title and deal "
        "title, merged and sorted by date desc, capped at `limit`. Each type is company-scoped "
        "exactly like its own list endpoint (hidden competition preserved). A query shorter than "
        "2 characters returns an empty list without touching the DB."
    ),
    parameters=[
        OpenApiParameter(
            name="q",
            description="Search query (min 2 chars; shorter → empty results). Required.",
            type=str,
            location=OpenApiParameter.QUERY,
            required=True,
        ),
        OpenApiParameter(
            name="limit",
            description="Number of documents to return (1..20, clamped). Default 8.",
            type=int,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: inline_serializer(
            "SearchDocumentsResponse",
            fields={
                "results": drf_serializers.ListField(
                    child=inline_serializer(
                        "SearchDocument",
                        fields={
                            "type": drf_serializers.ChoiceField(
                                choices=["quote", "contract", "invoice", "act", "generated"]
                            ),
                            "id": drf_serializers.IntegerField(),
                            "label": drf_serializers.CharField(),
                            "status_code": drf_serializers.CharField(allow_null=True),
                            "date": drf_serializers.DateTimeField(),
                            "deal": drf_serializers.IntegerField(allow_null=True),
                        },
                    )
                )
            },
        )
    },
    tags=["Analytics"],
)
class SearchDocumentsView(APIView):
    """Сквозной поиск по документам — global document search for the «единая станция документов».
    GET /api/v1/crm/analytics/search-documents/?q=<str>&limit=8

    Thin wrapper (Rule 8): pass query + limit → ONE service call → return. All company-scoping
    (incl. the hidden-competition boundary) lives in crm.services.document_search.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from crm.services.document_search import search_documents

        results = search_documents(
            request.user,
            request,
            q=request.query_params.get("q"),
            limit=request.query_params.get("limit"),
        )
        return Response({"results": results})
