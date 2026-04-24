"""
Admin Platform API: endpoints consumed exclusively by the React Platform Admin
SPA (PlatformAdminShell). All views require IsPlatformAdmin.

Exposes:
  GET /api/v1/admin/queue/      — unified triage queue (KYC, role apps, billing, tickets)
  GET /api/v1/admin/pulse/      — time-series pulse metrics (companies, deals, MRR)
  GET /api/v1/admin/search/     — cross-entity search (companies, users, deals, tickets, offers)
  GET /api/v1/admin/activity/   — ActivityLog scoped to a single entity

All data is derived from real DB models via ORM. No hardcoded rows, no fakes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import (
    OpenApiParameter, OpenApiResponse, extend_schema,
)

from core.permissions import IsPlatformAdmin


# ---------------------------------------------------------------------------
# Triage Queue
# ---------------------------------------------------------------------------

def _fmt_age(created: datetime | None) -> str:
    if not created:
        return ''
    delta = timezone.now() - created
    if delta.days >= 1:
        return f'{delta.days}d'
    hours = delta.seconds // 3600
    if hours:
        return f'{hours}h'
    minutes = max(1, delta.seconds // 60)
    return f'{minutes}m'


def _queue_kyc() -> list[dict[str, Any]]:
    from accounts.models import Company
    qs = (
        Company.objects
        .select_related('verification_status')
        .filter(verification_status__code='PROFILE_SUBMITTED')
        .order_by('created_at')
    )
    return [
        {
            'queue_type': 'kyc_pending',
            'entity_type': 'company',
            'entity_id': c.id,
            'title': c.name or f'Company #{c.id}',
            'subtitle': f'INN {c.inn}' if c.inn else '',
            'severity': 'warning',
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'age': _fmt_age(c.created_at),
            'actions': ['approve_kyc_l2', 'revoke_kyc', 'view'],
            'link': f'/admin/companies/{c.id}',
        }
        for c in qs
    ]


def _queue_role_applications() -> list[dict[str, Any]]:
    from accounts.models import CompanyRoleApplication
    qs = (
        CompanyRoleApplication.objects
        .select_related('company', 'requested_type', 'submitted_by')
        .filter(status__in=['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'])
        .order_by('created_at')
    )
    return [
        {
            'queue_type': 'role_application',
            'entity_type': 'role_application',
            'entity_id': a.id,
            'title': f'{a.company.name} → {a.requested_type.name}',
            'subtitle': a.get_status_display(),
            'severity': 'info' if a.status == 'PENDING' else 'warning',
            'created_at': a.created_at.isoformat() if a.created_at else None,
            'age': _fmt_age(a.created_at),
            'actions': ['approve_role', 'reject_role', 'view'],
            'link': f'/admin/role-apps?focus={a.id}',
        }
        for a in qs
    ]


def _queue_subscriptions() -> list[dict[str, Any]]:
    from accounts.models import SupplierSubscription
    now = timezone.now()
    soon = now + timedelta(days=7)
    past_due = (
        SupplierSubscription.objects.select_related('company')
        .filter(status='PAST_DUE')
        .order_by('valid_until')
    )
    expiring = (
        SupplierSubscription.objects.select_related('company')
        .filter(
            status__in=['ACTIVE', 'TRIAL'],
            valid_until__isnull=False,
            valid_until__lte=soon.date(),
            valid_until__gte=now.date(),
        )
        .order_by('valid_until')
    )
    items: list[dict[str, Any]] = []
    for s in past_due:
        items.append({
            'queue_type': 'subscription_past_due',
            'entity_type': 'subscription',
            'entity_id': s.id,
            'title': s.company.name if s.company else f'Subscription #{s.id}',
            'subtitle': f'{s.plan} · past due since {s.valid_until}' if s.valid_until else s.plan,
            'severity': 'critical',
            'created_at': s.valid_until.isoformat() if s.valid_until else None,
            'age': _fmt_age(datetime.combine(s.valid_until, datetime.min.time(), tzinfo=timezone.get_current_timezone())) if s.valid_until else '',
            'actions': ['activate_subscription', 'suspend_subscription', 'view'],
            'link': f'/admin/subscriptions?focus={s.id}',
        })
    for s in expiring:
        items.append({
            'queue_type': 'subscription_expiring',
            'entity_type': 'subscription',
            'entity_id': s.id,
            'title': s.company.name if s.company else f'Subscription #{s.id}',
            'subtitle': f'{s.plan} · expires {s.valid_until}',
            'severity': 'warning',
            'created_at': s.valid_until.isoformat() if s.valid_until else None,
            'age': _fmt_age(datetime.combine(s.valid_until, datetime.min.time(), tzinfo=timezone.get_current_timezone())) if s.valid_until else '',
            'actions': ['activate_subscription', 'view'],
            'link': f'/admin/subscriptions?focus={s.id}',
        })
    return items


def _queue_invoices() -> list[dict[str, Any]]:
    from crm.models import Invoice
    today = timezone.now().date()
    qs = (
        Invoice.objects.select_related('contract', 'contract__deal', 'contract__deal__company')
        .filter(
            status__in=['ISSUED', 'PARTIAL', 'OVERDUE'],
            due_date__lt=today,
        )
        .order_by('due_date')
    )
    items: list[dict[str, Any]] = []
    for inv in qs:
        company_name = (
            inv.contract.deal.company.name
            if inv.contract_id and inv.contract.deal_id and inv.contract.deal.company_id
            else ''
        )
        items.append({
            'queue_type': 'invoice_overdue',
            'entity_type': 'invoice',
            'entity_id': inv.id,
            'title': f'{inv.number} · {company_name}'.strip(' ·'),
            'subtitle': f'{inv.total_incl_vat} · due {inv.due_date}',
            'severity': 'critical',
            'created_at': inv.due_date.isoformat() if inv.due_date else None,
            'age': _fmt_age(datetime.combine(inv.due_date, datetime.min.time(), tzinfo=timezone.get_current_timezone())) if inv.due_date else '',
            'actions': ['view'],
            'link': f'/admin/deals/{inv.contract.deal_id}' if inv.contract_id and inv.contract.deal_id else '/admin/deals',
        })
    return items


def _queue_supplier_bids() -> list[dict[str, Any]]:
    """Submitted supplier bids awaiting buyer/admin review."""
    from crm.models import SupplierBid
    qs = (
        SupplierBid.objects
        .select_related('deal', 'supplier', 'deal__company')
        .filter(status='SUBMITTED')
        .order_by('submitted_at')
    )
    return [
        {
            'queue_type': 'supplier_bid_pending',
            'entity_type': 'supplier_bid',
            'entity_id': b.id,
            'title': f'Bid #{b.id} · {b.supplier.name if b.supplier_id else "?"}',
            'subtitle': (
                f'Deal #{b.deal_id} '
                f'{b.deal.title or ""} · {b.total_amount} '
                f'· lead {b.lead_time_days or "?"}d'
            ).strip(),
            'severity': 'info',
            'created_at': b.submitted_at.isoformat() if b.submitted_at else None,
            'age': _fmt_age(b.submitted_at),
            'actions': ['accept_bid', 'reject_bid', 'view'],
            'link': f'/admin/bids?focus={b.id}',
        }
        for b in qs
    ]


def _queue_support() -> list[dict[str, Any]]:
    from core.models import SupportTicket
    qs = (
        SupportTicket.objects.select_related('company', 'created_by')
        .filter(
            priority__in=[SupportTicket.PRIORITY_HIGH, SupportTicket.PRIORITY_URGENT],
            status__in=[SupportTicket.STATUS_OPEN, SupportTicket.STATUS_IN_PROGRESS],
        )
        .order_by('-priority', 'created_at')
    )
    return [
        {
            'queue_type': 'support_urgent',
            'entity_type': 'support_ticket',
            'entity_id': t.id,
            'title': t.subject,
            'subtitle': f'{t.company.name} · {t.get_priority_display()}' if t.company_id else t.get_priority_display(),
            'severity': 'critical' if t.priority == SupportTicket.PRIORITY_URGENT else 'warning',
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'age': _fmt_age(t.created_at),
            'actions': ['view'],
            'link': f'/admin/support?focus={t.id}',
        }
        for t in qs
    ]


SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}


@extend_schema(
    summary='Admin triage queue',
    description='Unified list of items requiring platform admin attention: KYC pending, '
                'role applications, subscriptions past-due/expiring, overdue invoices, urgent '
                'support tickets. Sorted by severity then oldest first.',
    parameters=[
        OpenApiParameter(name='queue_type', description='Filter by queue_type code', required=False, type=str),
        OpenApiParameter(name='limit', description='Max items to return (default 200)', required=False, type=int),
    ],
    responses={200: OpenApiResponse(description='Queue items')},
    tags=['Admin'],
)
class AdminTriageQueueView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        qt_filter = request.query_params.get('queue_type') or ''
        try:
            limit = min(int(request.query_params.get('limit', 200)), 500)
        except (TypeError, ValueError):
            limit = 200
        collectors = [
            _queue_kyc, _queue_role_applications, _queue_subscriptions,
            _queue_invoices, _queue_support, _queue_supplier_bids,
        ]
        items: list[dict[str, Any]] = []
        for collect in collectors:
            try:
                items.extend(collect())
            except Exception:  # pragma: no cover — don't let one source break the whole queue
                continue
        if qt_filter:
            items = [i for i in items if i.get('queue_type') == qt_filter]
        items.sort(key=lambda i: (
            SEVERITY_ORDER.get(i.get('severity', 'info'), 3),
            i.get('created_at') or '',
        ))
        totals: dict[str, int] = {}
        for i in items:
            key = i['queue_type']
            totals[key] = totals.get(key, 0) + 1
        return Response({
            'count': len(items),
            'totals': totals,
            'items': items[:limit],
        })


# ---------------------------------------------------------------------------
# Pulse (time-series)
# ---------------------------------------------------------------------------

VALID_PERIODS = {'7d': 7, '30d': 30, '90d': 90}


def _daily_series(qs, date_field: str, days: int, value_aggr=None) -> list[dict[str, Any]]:
    """Group a queryset by day into a dense series [{date, count, value}]."""
    today = timezone.now().date()
    start = today - timedelta(days=days - 1)
    annotated = (
        qs.filter(**{f'{date_field}__date__gte': start})
        .annotate(d=TruncDate(date_field))
        .values('d')
        .annotate(c=Count('id'))
    )
    if value_aggr is not None:
        annotated = annotated.annotate(v=value_aggr)
    by_date: dict[date, dict[str, Any]] = {row['d']: row for row in annotated if row.get('d')}
    series: list[dict[str, Any]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        row = by_date.get(d, {})
        series.append({
            'date': d.isoformat(),
            'count': int(row.get('c') or 0),
            'value': str(row.get('v') or '0'),
        })
    return series


@extend_schema(
    summary='Admin pulse metrics',
    description='Daily time-series for the admin dashboard: new companies, new deals (count + value), '
                'and monthly recurring revenue base (subscription monthly_rate sum of ACTIVE subs) by day.',
    parameters=[
        OpenApiParameter(name='period', description='7d | 30d | 90d', required=False, type=str),
    ],
    responses={200: OpenApiResponse(description='Pulse payload')},
    tags=['Admin'],
)
class AdminPulseView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        period = request.query_params.get('period', '30d')
        days = VALID_PERIODS.get(period, 30)
        from accounts.models import Company, SupplierSubscription
        from crm.models import Deal, Quote

        companies_series = _daily_series(
            Company.objects.all(), 'created_at', days,
        )
        deals_series = _daily_series(
            Deal.objects.all(), 'created_at', days,
        )
        quotes_series = _daily_series(
            Quote.objects.filter(status__code__in=['SENT', 'APPROVED']),
            'created_at', days,
            value_aggr=Coalesce(Sum('total_incl_vat'), Value(Decimal('0'))),
        )

        active_subs = SupplierSubscription.objects.filter(status__in=['ACTIVE', 'TRIAL'])
        mrr = active_subs.aggregate(total=Coalesce(Sum('monthly_rate'), Value(Decimal('0'))))['total'] or Decimal('0')

        return Response({
            'period': period,
            'days': days,
            'companies': companies_series,
            'deals': deals_series,
            'quotes_signed_value': quotes_series,
            'mrr': str(mrr),
            'active_subscriptions': active_subs.count(),
        })


# ---------------------------------------------------------------------------
# Cross-entity search
# ---------------------------------------------------------------------------

@extend_schema(
    summary='Admin cross-entity search',
    description='Fuzzy admin search across companies, users, deals, supplier offers, and support tickets.',
    parameters=[
        OpenApiParameter(name='q', description='Search term (min 2 chars)', required=True, type=str),
        OpenApiParameter(name='per_group', description='Results per group (default 5, max 20)', required=False, type=int),
    ],
    responses={200: OpenApiResponse(description='Grouped search results')},
    tags=['Admin'],
)
class AdminSearchView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'q': q, 'groups': []})
        try:
            per_group = min(int(request.query_params.get('per_group', 5)), 20)
        except (TypeError, ValueError):
            per_group = 5

        from accounts.models import Company, CustomUser
        from catalog.models import SupplierOffer
        from core.models import SupportTicket
        from crm.models import Deal

        companies = Company.objects.filter(
            Q(name__icontains=q) | Q(inn__icontains=q) | Q(email__icontains=q)
        ).order_by('name')[:per_group]
        users = CustomUser.objects.filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
        ).order_by('email')[:per_group]
        deals = Deal.objects.select_related('company', 'stage').filter(
            Q(title__icontains=q) | Q(id__iexact=q if q.isdigit() else '')
        ).order_by('-updated_at')[:per_group]
        offers = SupplierOffer.objects.select_related('product', 'supplier').filter(
            Q(supplier_sku__icontains=q) | Q(product__name__icontains=q)
        ).order_by('product__name')[:per_group]
        tickets = SupportTicket.objects.select_related('company').filter(
            Q(subject__icontains=q) | Q(description__icontains=q)
        ).order_by('-created_at')[:per_group]

        groups = []
        if companies:
            groups.append({
                'type': 'company',
                'label': 'companies',
                'items': [
                    {
                        'id': c.id,
                        'title': c.name,
                        'subtitle': c.inn or c.email or '',
                        'link': f'/admin/companies/{c.id}',
                    } for c in companies
                ],
            })
        if users:
            groups.append({
                'type': 'user',
                'label': 'users',
                'items': [
                    {
                        'id': u.id,
                        'title': u.get_full_name() or u.email,
                        'subtitle': u.email,
                        'link': f'/admin/users/{u.id}',
                    } for u in users
                ],
            })
        if deals:
            groups.append({
                'type': 'deal',
                'label': 'deals',
                'items': [
                    {
                        'id': d.id,
                        'title': d.title or f'Deal #{d.id}',
                        'subtitle': ' · '.join(filter(None, [
                            d.company.name if d.company_id else '',
                            d.stage.name if d.stage_id else '',
                        ])),
                        'link': f'/admin/deals/{d.id}',
                    } for d in deals
                ],
            })
        if offers:
            groups.append({
                'type': 'offer',
                'label': 'offers',
                'items': [
                    {
                        'id': o.id,
                        'title': f'{o.supplier_sku} · {o.product.name if o.product_id else ""}',
                        'subtitle': o.supplier.name if o.supplier_id else '',
                        'link': f'/admin/offers?focus={o.id}',
                    } for o in offers
                ],
            })
        if tickets:
            groups.append({
                'type': 'support_ticket',
                'label': 'tickets',
                'items': [
                    {
                        'id': t.id,
                        'title': t.subject,
                        'subtitle': f'{t.get_status_display()} · {t.get_priority_display()}',
                        'link': f'/admin/support?focus={t.id}',
                    } for t in tickets
                ],
            })
        return Response({'q': q, 'groups': groups})


# ---------------------------------------------------------------------------
# Entity-scoped activity log
# ---------------------------------------------------------------------------

@extend_schema(
    summary='Entity-scoped activity log',
    description='Returns ActivityLog entries filtered by entity_type + entity_id. '
                'Used by the Timeline tab on admin detail pages.',
    parameters=[
        OpenApiParameter(name='entity_type', description='Entity code (company, user, deal, subscription, role_application)', required=True, type=str),
        OpenApiParameter(name='entity_id', description='Entity primary key', required=True, type=int),
        OpenApiParameter(name='level', description='Filter by severity level', required=False, type=str),
        OpenApiParameter(name='limit', description='Max items (default 100, max 500)', required=False, type=int),
    ],
    responses={200: OpenApiResponse(description='Activity log entries')},
    tags=['Admin'],
)
class AdminActivityView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        entity_type = (request.query_params.get('entity_type') or '').strip()
        entity_id_raw = request.query_params.get('entity_id')
        if not entity_type or not entity_id_raw:
            return Response({'detail': 'entity_type and entity_id are required'}, status=400)
        try:
            entity_id = int(entity_id_raw)
        except (TypeError, ValueError):
            return Response({'detail': 'entity_id must be integer'}, status=400)

        try:
            limit = min(int(request.query_params.get('limit', 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        from crm.models import ActivityLog
        qs = (
            ActivityLog.objects.select_related('user')
            .filter(entity_type=entity_type, entity_id=entity_id)
            .order_by('-timestamp')
        )
        level = request.query_params.get('level')
        if level:
            qs = qs.filter(level=level)

        items = [
            {
                'id': log.id,
                'action': log.action,
                'detail': log.detail,
                'level': log.level,
                'reason': log.reason,
                'before_data': log.before_data,
                'after_data': log.after_data,
                'user_id': log.user_id,
                'user_email': log.user.email if log.user else None,
                'user_name': log.user.get_full_name() if log.user else '',
                'timestamp': log.timestamp.isoformat(),
            }
            for log in qs[:limit]
        ]
        return Response({
            'entity_type': entity_type,
            'entity_id': entity_id,
            'count': len(items),
            'items': items,
        })
