"""KPI дашборда — вся логика подсчёта (Rule 8).

Раньше эти ~340 строк жили приватными методами внутри `DashboardAnalyticsView`, хотя три
соседние вьюхи того же файла уже были тонкими обёртками над сервисами. Теперь вьюха
однородна с ними: разобрать параметры → ОДИН вызов → Response.

**Изоляция данных B2B** — три взаимоисключающие области видимости:

* платформенный оператор → видит всё (`company_ids=None`, `deal_scope=None`);
* продавец в своём контексте → область задают РОУТИНГОВЫЕ id сделок, а не компания-покупатель.
  Продавец не состоит в `deal.company` покупателя, поэтому прежний фильтр `company_id__in`
  давал чистому продавцу НУЛЕВЫЕ KPI. Роутинговые сделки и есть граница конфиденциальности
  продавца (`DealSellerRouting`);
* покупатель (и двойной пользователь в контексте покупателя) → область по своим компаниям.

Кэш живёт здесь же, а не во вьюхе: иначе следующий вызывающий сервис прошёл бы мимо него.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone

from accounts.constants import CompanyTypeCode
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Deal, Quote

CACHE_TTL_SECONDS = 60
DEFAULT_PERIOD = "30d"
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
REQUEST_COMPLETION_GOAL = 80
DEALS_BY_MONTH_WINDOW_DAYS = 180
ACTIVITY_WINDOW_DAYS = 30
TOP_PRODUCTS_LIMIT = 5

CLOSED_STAGES = [DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST]


class DashboardScope:
    """Разрешённая область видимости пользователя — то, чем ограничены ВСЕ запросы ниже."""

    __slots__ = ("is_staff", "deal_scope", "seller_company_ids", "user_company_ids")

    def __init__(self, is_staff, deal_scope, seller_company_ids, user_company_ids):
        self.is_staff = is_staff
        self.deal_scope = deal_scope
        self.seller_company_ids = seller_company_ids
        self.user_company_ids = user_company_ids


def resolve_scope(user, request) -> DashboardScope:
    """Определить область видимости по действующему контексту (см. модульный докстринг)."""
    from accounts.services.permissions import seller_acting_company_ids, seller_visible_deal_ids

    is_staff = user.is_platform_admin
    deal_scope = None if is_staff else seller_visible_deal_ids(user, request)
    # Собственные компании действующего продавца — ими ограничивается KPI каталога
    # (аудит E4: раньше считался Product.owner_company и показывал 0).
    seller_company_ids = None if is_staff else seller_acting_company_ids(user, request)
    if is_staff or deal_scope is not None:
        user_company_ids = None
    else:
        user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    return DashboardScope(is_staff, deal_scope, seller_company_ids, user_company_ids)


def scope_deals(deals, scope: DashboardScope):
    """Применить область видимости к queryset сделок.

    `deal_scope` (множество роутинговых id) выигрывает у действующего продавца;
    `user_company_ids` ограничивает покупателя своими компаниями; оба None = видно всё.
    """
    if scope.deal_scope is not None:
        return deals.filter(id__in=scope.deal_scope)
    if scope.user_company_ids is not None:
        return deals.filter(company_id__in=scope.user_company_ids)
    return deals


def resolve_period_start(period: str):
    """Строка периода (7d/30d/90d) → начальная дата."""
    return timezone.now() - timedelta(days=PERIOD_DAYS.get(period, PERIOD_DAYS[DEFAULT_PERIOD]))


def percentage_change(previous, current) -> float:
    """Процентное изменение между двумя значениями (0.0, если базы нет)."""
    if previous == 0:
        return 0.0
    return round(((current - previous) / abs(previous)) * 100, 1)


def _volume_kpis(period_deals, prev_period_deals, all_deals) -> dict:
    """Объём сделок и активные заявки с изменением период-к-периоду."""
    latest_quote = Quote.objects.filter(deal=OuterRef("pk")).order_by("-version").values("total_incl_vat")[:1]

    current_volume = period_deals.annotate(deal_value=Subquery(latest_quote)).aggregate(total=Sum("deal_value"))[
        "total"
    ] or Decimal("0")
    prev_volume = prev_period_deals.annotate(deal_value=Subquery(latest_quote)).aggregate(total=Sum("deal_value"))[
        "total"
    ] or Decimal("0")

    current_active = all_deals.exclude(stage__code__in=CLOSED_STAGES).count()
    prev_active = prev_period_deals.exclude(stage__code__in=CLOSED_STAGES).count()

    return {
        "deals_volume": float(current_volume),
        "deals_volume_change": percentage_change(prev_volume, current_volume),
        "active_requests": current_active,
        "active_requests_change": percentage_change(
            prev_active if prev_active > 0 else current_active,
            current_active,
        ),
    }


def _catalog_kpis(period_start, scope: DashboardScope) -> dict:
    """Размер каталога продавца («Активные позиции») с изменением период-к-периоду.

    Каталог продавца — это НЕ общий PIM (`catalog.Product` — кросс-тенантные мастер-данные),
    а живые офферы продавца: строки `SupplierOffer` с `is_active=True`. Это мировой стандарт
    продавецкого KPI (ср. «Active listings» Amazon Seller Central / «Products online» Alibaba)
    и починка аудита E4, где счёт по `Product.owner_company` показывал 0 при живых офферах.

    Область по контексту (аудит F4): оператор видит все активные офферы, продавец — только
    СВОИ, у покупателя их нет (KPI ему не показывается) → 0.
    """
    from catalog.models import SupplierOffer

    offers = SupplierOffer.objects.filter(is_active=True)
    if not scope.is_staff:
        offers = offers.filter(supplier_id__in=(scope.seller_company_ids or []))
    # ARCH-04: текущее и прошлое значения по ОДНОМУ queryset одним aggregate.
    counts = offers.aggregate(
        current=Count("id"),
        prev=Count("id", filter=Q(created_at__lt=period_start)),
    )
    return {
        "catalog_items": counts["current"],
        "catalog_items_change": percentage_change(counts["prev"], counts["current"]),
    }


def _client_kpis(period_start, scope: DashboardScope) -> dict:
    """Количество клиентов с изменением период-к-периоду.

    Область по контексту (аудит F4): оператор видит все компании-CLIENT, продавец — только
    различные компании-покупатели по зароутиненным на него сделкам, у покупателя «клиентов»
    нет → 0.
    """
    if scope.is_staff:
        from accounts.models import Company, CompanyType

        client_type = CompanyType.objects.filter(code=CompanyTypeCode.CLIENT).first()
        if not client_type:
            return {"clients_count": 0, "clients_count_change": 0}
        current_clients = Company.objects.filter(types=client_type).distinct().count()
        prev_clients = (
            current_clients - Company.objects.filter(types=client_type, created_at__gte=period_start).distinct().count()
        )
    elif scope.deal_scope is not None:
        routed = Deal.objects.filter(id__in=scope.deal_scope)
        current_clients = routed.values("company_id").distinct().count()
        # База = различные компании-покупатели, у которых зароутиненная сделка была УЖЕ ДО периода
        # (аудит M4). Прежняя арифметика «минус созданные в периоде» ошибочно выбрасывала
        # повторных клиентов (сделки в обоих периодах) и искажала стрелку тренда.
        prev_clients = routed.filter(created_at__lt=period_start).values("company_id").distinct().count()
    else:
        current_clients = prev_clients = 0
    return {
        "clients_count": current_clients,
        "clients_count_change": percentage_change(prev_clients, current_clients),
    }


def _counterparties() -> dict:
    """Разбивка компаний по типам — один запрос через values().annotate()."""
    from accounts.models import Company

    type_counts = dict(
        Company.objects.filter(
            types__code__in=[CompanyTypeCode.CLIENT, CompanyTypeCode.SUPPLIER],
        )
        .values_list("types__code")
        .annotate(
            count=Count("id", distinct=True),
        )
        .values_list("types__code", "count")
    )
    return {
        "manufacturers": type_counts.get(CompanyTypeCode.MANUFACTURER, 0),
        "buyers": type_counts.get(CompanyTypeCode.CLIENT, 0),
        "intermediaries": type_counts.get(CompanyTypeCode.SUPPLIER, 0),
    }


def _request_completion(scope: DashboardScope) -> float:
    """Процент закрытия заявок в пределах области видимости."""
    quotes_qs = Quote.objects.all()
    if scope.deal_scope is not None:
        quotes_qs = quotes_qs.filter(deal_id__in=scope.deal_scope)
    elif scope.user_company_ids is not None:
        quotes_qs = quotes_qs.filter(deal__company_id__in=scope.user_company_ids)
    # ARCH-04: закрытые и всего по ОДНОМУ queryset одним aggregate.
    counts = quotes_qs.aggregate(
        total=Count("id"),
        completed=Count(
            "id",
            filter=Q(status__code__in=[QuoteStatusCode.APPROVED, QuoteStatusCode.SENT]),
        ),
    )
    completed, total = counts["completed"], counts["total"]
    return round((completed / total * 100) if total > 0 else 0, 1)


def _buyer_stats(all_deals) -> dict:
    """Счётчики стадий для покупателя — три корзины одним aggregate (ARCH-04)."""
    counts = all_deals.aggregate(
        in_progress=Count(
            "id",
            filter=Q(stage__code__in=[DealStageCode.SOURCING, DealStageCode.CALCULATING]),
        ),
        received=Count("id", filter=Q(stage__code=DealStageCode.QUOTE_SENT)),
        completed=Count(
            "id",
            filter=Q(
                stage__code__in=[
                    DealStageCode.CLOSED_WON,
                    DealStageCode.CONTRACT_SIGNED,
                ]
            ),
        ),
    )
    return {
        "deals_in_progress": counts["in_progress"],
        "quotes_received": counts["received"],
        "deals_completed": counts["completed"],
    }


def _deals_by_month(deals) -> list:
    """Сделки по месяцам за последние полгода."""
    from django.db.models.functions import TruncMonth

    window_start = timezone.now() - timedelta(days=DEALS_BY_MONTH_WINDOW_DAYS)
    monthly_deals = (
        deals.filter(created_at__gte=window_start)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"), value=Sum("quotes__total_incl_vat"))
        .order_by("month")
    )
    return [
        {
            "month": item["month"].strftime("%Y-%m") if item.get("month") else "",
            "count": item["count"],
            "value": float(item.get("value") or 0),
        }
        for item in monthly_deals
    ]


def _activity_by_day(scope: DashboardScope) -> list:
    """Активность по дням за последний месяц в пределах области видимости."""
    from django.db.models.functions import TruncDate

    from crm.models import ActivityLog

    window_start = timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
    qs = ActivityLog.objects.filter(timestamp__gte=window_start)
    if scope.deal_scope is not None:
        qs = qs.filter(entity_type="deal", entity_id__in=scope.deal_scope)
    elif scope.user_company_ids is not None:
        qs = qs.filter(user__memberships__company_id__in=scope.user_company_ids)
    daily = qs.annotate(day=TruncDate("timestamp")).values("day").annotate(count=Count("id")).order_by("day")
    return [
        {
            # Дата (дд.мм), а не только день недели: в разреженном 30-дневном окне бывает
            # две разные пятницы, и «%a» рисовал неотличимый дубль «Пт/Пт».
            "day": item["day"].strftime("%d.%m") if item.get("day") else "",
            "count": item["count"],
        }
        for item in daily
    ]


def _top_products(scope: DashboardScope, limit: int = TOP_PRODUCTS_LIMIT) -> list:
    """Топ товаров по частоте появления в сделках, в пределах области видимости."""
    from catalog.models import Product

    qs = Product.objects.select_related("category")
    if scope.deal_scope is not None:
        qs = qs.filter(quote_items__quote__deal_id__in=scope.deal_scope)
    elif scope.user_company_ids is not None:
        qs = qs.filter(quote_items__quote__deal__company_id__in=scope.user_company_ids)
    top = qs.annotate(deal_count=Count("quote_items", distinct=True)).order_by("-deal_count")[:limit]
    return [
        {
            "id": str(product.id),
            "name": product.name,
            "quantity": product.deal_count,
            "category": product.category.name if product.category else "",
        }
        for product in top
    ]


def _compute(scope: DashboardScope, period: str) -> dict:
    """Собрать все KPI по разрешённой области видимости."""
    period_start = resolve_period_start(period)
    all_deals = scope_deals(Deal.objects.all(), scope)
    period_deals = all_deals.filter(created_at__gte=period_start)
    prev_period_start = period_start - (timezone.now() - period_start)
    prev_period_deals = scope_deals(
        Deal.objects.filter(created_at__gte=prev_period_start, created_at__lt=period_start),
        scope,
    )

    return {
        **_volume_kpis(period_deals, prev_period_deals, all_deals),
        **_catalog_kpis(period_start, scope),
        **_client_kpis(period_start, scope),
        "deals_by_month": _deals_by_month(all_deals),
        "activity_by_day": _activity_by_day(scope),
        "top_products": _top_products(scope),
        "counterparties": _counterparties(),
        "request_completion": _request_completion(scope),
        "request_completion_goal": REQUEST_COMPLETION_GOAL,
        **_buyer_stats(all_deals),
    }


def dashboard_analytics(user, request, period: str = DEFAULT_PERIOD) -> dict:
    """KPI дашборда для пользователя за период. Только чтение, результат кэшируется на минуту.

    Действующий контекст ОБЯЗАН входить в ключ кэша (аудит M3): `catalog_items` /
    `clients_count` зависят от контекста (продавец → свои товары / зароутиненные покупатели,
    покупатель → 0), поэтому двойной покупатель+продавец, переключивший контекст внутри
    60-секундного TTL, иначе прочитал бы цифры другого контекста.
    """
    from django.core.cache import cache

    from accounts.services.permissions import acting_context

    cache_key = f"dashboard_analytics_{period}_{acting_context(request) or 'NONE'}_{user.pk}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    data = _compute(resolve_scope(user, request), period)
    cache.set(cache_key, data, CACHE_TTL_SECONDS)
    return data
