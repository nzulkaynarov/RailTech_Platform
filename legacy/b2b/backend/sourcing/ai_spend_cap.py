"""Per-company daily AI-job spend cap (security audit #13).

The 8 interactive AI features all funnel through ``enqueue_ai_job`` (ARCH-01);
each enqueued job is a paid Anthropic call. Without a ceiling a runaway script or
an abusive tenant could run an unbounded bill. This module answers ONE question —
"has the requesting user's company already used its daily quota?" — so the
enqueue choke-point can refuse with a 429 BEFORE queuing the task or spending a
credit.

Design notes (deliberately kept boring — it is a safety fuse, not policy):
- TWO-TIER ceiling: a company with an operational SupplierSubscription gets the
  generous ``settings.AI_DAILY_JOB_CAP_PER_COMPANY`` (paying tenants never reach it);
  an unsubscribed / free company gets the tighter ``settings.AI_DAILY_JOB_CAP_FREE``
  so a free tenant can't run an unbounded Anthropic bill on the always-free features
  (ai.match / ai.preflight / extract / compose). Which tier applies is decided by the
  subscription alone — NOT by any single feature entitlement.
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


def _daily_cap_for_companies(company_ids) -> int:
    """Pick the applicable daily ceiling for the requesting user's companies.

    A company with an operational (ACTIVE/TRIAL, in-validity) SupplierSubscription is a
    paying tenant → the generous ``AI_DAILY_JOB_CAP_PER_COMPANY``. Otherwise → the tighter
    ``AI_DAILY_JOB_CAP_FREE``. A user in several companies gets the higher ceiling if ANY of
    them is subscribed (the shared job bucket already spans all their memberships). Logic
    lives here (Rule 8), not in the view.
    """
    from accounts.services import company_has_operational_subscription

    subscribed = any(company_has_operational_subscription(company_id) for company_id in company_ids)
    if subscribed:
        return getattr(settings, "AI_DAILY_JOB_CAP_PER_COMPANY", 0)
    return getattr(settings, "AI_DAILY_JOB_CAP_FREE", 0)


def is_ai_daily_cap_reached(user) -> bool:
    """True when the requesting user's company has hit the daily AI-job ceiling.

    Counts today's ``AIJob`` rows owned by any active member of the user's active companies
    and compares against the applicable two-tier ceiling (subscribed → ``AI_DAILY_JOB_CAP_PER_COMPANY``,
    free → ``AI_DAILY_JOB_CAP_FREE``). Returns False (never capped) for a disabled tier, platform
    admins, and users with no active company membership. Called at the enqueue choke-point.
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
