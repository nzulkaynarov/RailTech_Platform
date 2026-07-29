"""Per-company daily AI-job spend cap (security audit #13).

The 8 interactive AI features all funnel through ``enqueue_ai_job`` (ARCH-01);
each enqueued job is a paid Anthropic call. Without a ceiling a runaway script or
an abusive tenant could run an unbounded bill. This module answers ONE question —
"has the requesting user's company already used its daily quota?" — so the
enqueue choke-point can refuse with a 429 BEFORE queuing the task or spending a
credit.

Design notes (a safety fuse AND, now, a product lever):
- TIER-AWARE ceiling: each subscription plan maps to a daily allowance
  (``settings.AI_DAILY_CAP_{BASIC,STANDARD,PREMIUM}`` — Старт/Про/Безлимит); a company with no operational
  subscription falls back to the tighter ``settings.AI_DAILY_JOB_CAP_FREE`` so a free tenant
  can't run an unbounded Anthropic bill on the always-free features. The Безлимит plan (0/neg)
  disables the cap for that tenant.
- PER-COMPANY OVERRIDE: an operator can lift or throttle ONE tenant via a
  ``CompanyEntitlement(ai.daily_cap).limit`` row in React Admin (reuses the entitlement layer);
  the override number wins over the plan tier. This keeps promo / VIP / abuse-throttle out of
  code and in the operator's hands (owner decision 2026-07-28).
- The count comes straight from the persistent ``AIJob`` rows (no new Redis/DB
  state, no extra infra to keep consistent). One indexed COUNT per enqueue.
- Scope is the CALENDAR DAY in ``settings.TIME_ZONE`` and the requesting user's
  active company (the whole team shares one bucket — the bill is per company).
- Exempt (never capped): the applicable tier disabled (<= 0), platform admins (they
  don't act on behalf of a tenant), and users with no active company membership.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# plan code → the settings attribute holding its daily allowance (read LIVE via getattr so an env
# change / test override takes effect without rebuilding a module-level dict).
_PLAN_CAP_SETTING = {
    "BASIC": "AI_DAILY_CAP_BASIC",  # Старт
    "STANDARD": "AI_DAILY_CAP_STANDARD",  # Про
    "PREMIUM": "AI_DAILY_CAP_PREMIUM",  # Безлимит
}


def _plan_cap_for_company(company_id) -> int:
    """Tier allowance for ONE company: its operational subscription plan's daily cap (Старт/Про/
    Безлимит), or ``AI_DAILY_JOB_CAP_FREE`` when the company has no operational subscription.
    0/negative = UNLIMITED (the Безлимит / PREMIUM tier). An unknown/new plan code falls back to the
    generous per-company default so a paying tenant is never accidentally capped tighter than free."""
    from accounts.models import SupplierSubscription

    sub = SupplierSubscription.objects.filter(company_id=company_id).order_by("-updated_at").first()
    if sub is None or not sub.is_operational:
        return getattr(settings, "AI_DAILY_JOB_CAP_FREE", 0)
    fallback = getattr(settings, "AI_DAILY_JOB_CAP_PER_COMPANY", 0)
    setting_name = _PLAN_CAP_SETTING.get(sub.plan)
    return getattr(settings, setting_name, fallback) if setting_name else fallback


def _override_cap_for_company(company_id):
    """Per-company operator OVERRIDE of the daily AI ceiling, or ``None`` when unset.

    Reuses the (previously dormant) ``CompanyEntitlement.limit`` field on an ``ai.daily_cap`` row
    an operator edits in React Admin — so support can lift or throttle ONE tenant without touching
    plan tiers. Only a currently-granted row with a POSITIVE limit counts (limit 0/absent → no
    override, fall through to the plan tier; per-company "unlimited" is expressed via the Безлимит
    plan, not a 0 here). The number wins over the plan tier."""
    from accounts.constants import FeatureKey
    from accounts.models import CompanyEntitlement

    row = (
        CompanyEntitlement.objects.filter(company_id=company_id, feature_key=FeatureKey.AI_DAILY_CAP.value)
        .only("access", "limit", "expires_at", "credits")
        .first()
    )
    if row is None or not row.limit or not row.is_currently_granted():
        return None
    return row.limit


def _effective_cap_for_company(company_id) -> int:
    """A company's daily ceiling: operator override (if any) wins over the plan tier."""
    override = _override_cap_for_company(company_id)
    return override if override is not None else _plan_cap_for_company(company_id)


def _daily_cap_for_companies(company_ids) -> int:
    """The applicable daily ceiling across the requesting user's companies. Resolution per
    company: operator override → subscription-plan tier → free floor. A user in several companies
    gets the MOST GENEROUS ceiling (UNLIMITED if ANY company is on the Безлимит tier / disabled) —
    the shared job bucket already spans all their memberships. Logic lives here (Rule 8)."""
    caps = [_effective_cap_for_company(company_id) for company_id in company_ids]
    if not caps:
        return getattr(settings, "AI_DAILY_JOB_CAP_FREE", 0)
    if any(cap <= 0 for cap in caps):
        return 0  # unlimited (Безлимит tier / opt-out) wins over any finite ceiling
    return max(caps)


def is_ai_daily_cap_reached(user) -> bool:
    """True when the requesting user's company has hit the daily AI-job ceiling.

    Counts today's ``AIJob`` rows owned by any active member of the user's active companies and
    compares against the applicable ceiling, resolved per company as: operator override
    (``CompanyEntitlement(ai.daily_cap).limit``) → subscription-plan tier (Старт/Про/Безлимит) →
    ``AI_DAILY_JOB_CAP_FREE``. Returns False (never capped) for a disabled tier, platform admins,
    and users with no active company membership. Called at the enqueue choke-point.
    """
    if getattr(user, "is_platform_admin", False):
        return False

    # Local imports keep this module free of app-load ordering / circular-import risk.
    from accounts.models import CompanyMember

    from .models import AIJob

    company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    if not company_ids:
        # No tenant to bill against — a lone / platform user is not an abuse vector here.
        return False

    cap = _daily_cap_for_companies(company_ids)
    if cap <= 0:
        # The applicable tier is disabled (opt-out) — never capped.
        return False

    # The bill is per company: the whole team shares one daily bucket, so count every
    # active member's jobs, not just the caller's.
    member_user_ids = CompanyMember.objects.filter(
        company_id__in=company_ids,
        is_active=True,
    ).values_list("user_id", flat=True)

    start_of_day = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = AIJob.objects.filter(
        owner_id__in=member_user_ids,
        created_at__gte=start_of_day,
    ).count()

    if used_today >= cap:
        logger.warning(
            "AI daily cap reached: company_ids=%s used=%s cap=%s (user=%s)",
            list(company_ids),
            used_today,
            cap,
            getattr(user, "id", None),
        )
        return True
    return False
