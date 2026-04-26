import json

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Sum
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from accounts.models import Company, CompanyRoleApplication, CustomUser
from crm.models import Deal, Lead, Quote, QuoteItem

# Dashboard payload is recomputed every DASHBOARD_CACHE_TTL seconds.
# 5 minutes: fresh-enough for KPI read from Ops, avoids hammering Neon on every
# /admin/ page load (every click counts the same aggregates otherwise).
DASHBOARD_CACHE_TTL = 300
DASHBOARD_CACHE_KEY_PREFIX = "admin:dashboard:v2"

# Palette for Chart.js — matches Unfold's primary/accent scale + semantic tokens.
# One colour per dataset bar; Chart.js cycles if labels > colours.
_CHART_PALETTE = [
    "#2563eb",  # primary
    "#10b981",  # success
    "#f59e0b",  # warning
    "#ef4444",  # danger
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#ec4899",  # pink
]


def _chart_json(labels: list, data: list, label: str) -> str:
    """Serialize a chart config into a JSON string ready for Chart.js data-value."""
    payload = {
        "labels": [str(lbl) for lbl in labels],
        "datasets": [
            {
                "label": str(label),
                "data": data,
                "backgroundColor": [_CHART_PALETTE[i % len(_CHART_PALETTE)] for i in range(len(data))],
                "borderRadius": 6,
                "borderSkipped": False,
                "maxBarThickness": 64,
            }
        ],
    }
    return json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False)


_CHART_OPTIONS_JSON = json.dumps(
    {
        # Fill the card height instead of honouring Chart.js's default 2:1 aspect.
        "responsive": True,
        "maintainAspectRatio": False,
        # Remove Chart.js's default ~8px padding around the plot area — cards are
        # already using Unfold's p-6, any extra internal padding reads as dead space.
        "layout": {"padding": {"top": 4, "right": 0, "bottom": 0, "left": 0}},
        "plugins": {"legend": {"display": False}},
        "scales": {
            "y": {"beginAtZero": True, "grid": {"drawBorder": False}},
            "x": {"grid": {"display": False}, "ticks": {"padding": 4}},
        },
    }
)


def dashboard_callback(request, context):
    """RailTech B2B Control Center Dashboard.

    Wraps the heavy computation in Django cache (5-min TTL). Cache key includes
    current thread-local language so RU/EN sessions don't poison each other.
    Lazy-translated strings inside the payload survive pickling: Promise objects
    re-evaluate on render.
    """
    lang = translation.get_language() or "ru"
    cache_key = f"{DASHBOARD_CACHE_KEY_PREFIX}:{lang}"
    payload = cache.get(cache_key)
    if payload is None:
        payload = _compute_dashboard_payload()
        cache.set(cache_key, payload, DASHBOARD_CACHE_TTL)
    context.update(payload)
    return context


def _compute_dashboard_payload() -> dict:
    """Build stats + charts dict. Extracted for caching; see dashboard_callback."""

    # ─── KPI Metrics ───

    # 1. Pipeline value (SENT + APPROVED quotes)
    pipeline_value = (
        Quote.objects.filter(status__code__in=["SENT", "APPROVED"]).aggregate(total=Sum("total_incl_vat"))["total"] or 0
    )

    # 2. Active deals count
    active_deals = Deal.objects.exclude(stage__code__in=["CLOSED_WON", "CLOSED_LOST"]).count()

    # 3. KYC pending
    kyc_pending = Company.objects.filter(verification_status__code="PROFILE_SUBMITTED").count()

    # 4. Role applications pending
    role_apps_pending = CompanyRoleApplication.objects.filter(
        status__in=["PENDING", "DOCUMENTS_REQUIRED", "PAYMENT_REQUIRED"]
    ).count()

    # 5. Unprocessed leads
    unprocessed_leads = Lead.objects.filter(is_processed=False).count()

    # 6. Sourcing backlog (unmatched items)
    sourcing_backlog = QuoteItem.objects.filter(product__isnull=True).count()

    # 7. Total companies
    total_companies = Company.objects.count()

    # 8. Productivity (quotes per active manager)
    managers_count = CustomUser.objects.filter(role__code="ADMIN").count()
    total_quotes = Quote.objects.count()
    productivity = round(total_quotes / managers_count, 1) if managers_count > 0 else 0

    # ─── Charts ───

    # Deal funnel
    deal_stats = list(
        Deal.objects.values("stage__name").annotate(count=Count("id")).filter(count__gt=0).order_by("stage__sort_order")
    )

    # Revenue by country (approved quotes)
    region_stats = list(
        Quote.objects.filter(status__code="APPROVED", tax_country__isnull=False)
        .values("tax_country__name")
        .annotate(revenue=Sum("total_incl_vat"))
        .order_by("-revenue")[:5]
    )

    return {
        "stats": [
            {
                "title": _("Воронка продаж"),
                "metric": f"{pipeline_value:,.0f} UZS",
                "icon": "payments",
                "link": "/admin/crm/quote/",
            },
            {
                "title": _("Активные сделки"),
                "metric": active_deals,
                "icon": "handshake",
                "link": "/admin/crm/deal/",
            },
            {
                "title": _("Компании"),
                "metric": total_companies,
                "icon": "domain",
                "link": "/admin/accounts/company/",
            },
            {
                "title": _("Ожидают KYC"),
                "metric": kyc_pending,
                "icon": "verified_user",
                "link": "/admin/accounts/company/?verification_status__code__exact=PROFILE_SUBMITTED",
            },
            {
                "title": _("Заявки на роли"),
                "metric": role_apps_pending,
                "icon": "assignment",
                "link": "/admin/accounts/companyroleapplication/?status__exact=PENDING",
            },
            {
                "title": _("Новые лиды"),
                "metric": unprocessed_leads,
                "icon": "contact_page",
                "link": "/admin/crm/lead/?is_processed__exact=0",
            },
            {
                "title": _("Нераспознанные позиции"),
                "metric": sourcing_backlog,
                "icon": "help_outline",
            },
            {
                "title": _("КП / менеджер"),
                "metric": f"{productivity}",
                "icon": "speed",
            },
        ],
        "charts": [
            {
                "title": _("Воронка сделок"),
                "data": _chart_json(
                    labels=[s["stage__name"] or _("Без стадии") for s in deal_stats],
                    data=[s["count"] for s in deal_stats],
                    label=_("Сделки"),
                ),
                "options": _CHART_OPTIONS_JSON,
                "empty": not deal_stats,
            },
            {
                "title": _("Выручка по регионам (UZS)"),
                "data": _chart_json(
                    labels=[s["tax_country__name"] for s in region_stats],
                    data=[float(s["revenue"] or 0) for s in region_stats],
                    label=_("Сумма"),
                ),
                "options": _CHART_OPTIONS_JSON,
                "empty": not region_stats,
            },
        ],
    }
