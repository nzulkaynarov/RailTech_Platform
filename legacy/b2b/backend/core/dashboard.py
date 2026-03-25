from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Count, Q
from accounts.models import Company, CustomUser, CompanyRoleApplication
from crm.models import Deal, DealStage, Lead, Quote, QuoteStatus, QuoteItem


def dashboard_callback(request, context):
    """
    RailTech B2B Control Center Dashboard.
    Unfold 0.84+ compatible structure.
    """

    # ─── KPI Metrics ───

    # 1. Pipeline value (SENT + APPROVED quotes)
    pipeline_value = Quote.objects.filter(
        status__code__in=['SENT', 'APPROVED']
    ).aggregate(total=Sum('total_incl_vat'))['total'] or 0

    # 2. Active deals count
    active_deals = Deal.objects.exclude(
        stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
    ).count()

    # 3. KYC pending
    kyc_pending = Company.objects.filter(
        verification_status__code='PROFILE_SUBMITTED'
    ).count()

    # 4. Role applications pending
    role_apps_pending = CompanyRoleApplication.objects.filter(
        status__in=['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED']
    ).count()

    # 5. Unprocessed leads
    unprocessed_leads = Lead.objects.filter(is_processed=False).count()

    # 6. Sourcing backlog (unmatched items)
    sourcing_backlog = QuoteItem.objects.filter(product__isnull=True).count()

    # 7. Total companies
    total_companies = Company.objects.count()

    # 8. Productivity (quotes per active manager)
    managers_count = CustomUser.objects.filter(
        role__isnull=False, role__is_staff_level=True
    ).count()
    total_quotes = Quote.objects.count()
    productivity = round(total_quotes / managers_count, 1) if managers_count > 0 else 0

    # ─── Charts ───

    # Deal funnel
    deal_stats = list(
        Deal.objects.values('stage__name').annotate(
            count=Count('id')
        ).filter(count__gt=0).order_by('stage__sort_order')
    )

    # Revenue by country (approved quotes)
    region_stats = list(
        Quote.objects.filter(
            status__code='APPROVED',
            tax_country__isnull=False
        ).values('tax_country__name').annotate(
            revenue=Sum('total_incl_vat')
        ).order_by('-revenue')[:5]
    )

    context.update({
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
                "labels": [s["stage__name"] or "Без стадии" for s in deal_stats],
                "datasets": [{
                    "label": _("Сделки"),
                    "data": [s["count"] for s in deal_stats],
                }]
            },
            {
                "title": _("Выручка по регионам"),
                "labels": [s["tax_country__name"] for s in region_stats],
                "datasets": [{
                    "label": _("Сумма (UZS)"),
                    "data": [float(s["revenue"]) for s in region_stats],
                }]
            }
        ],
    })

    return context
