"""Per-company daily AI-job spend cap (security audit #13).

The 8 interactive AI features all funnel through ``enqueue_ai_job`` (ARCH-01);
each enqueued job is a paid Anthropic call. Without a ceiling a runaway script or
an abusive tenant could run an unbounded bill. This module answers ONE question —
"has the requesting user's company already used its daily quota?" — so the
enqueue choke-point can refuse with a 429 BEFORE queuing the task or spending a
credit. The same numbers answer a second, purely informational question —
"сколько осталось на сегодня?" (``ai_daily_usage``) — которую ``/me`` показывает в
интерфейсе: аудит R4 §7.4, механизм был, не хватало ВИДИМОСТИ (пользователь узнавал
о лимите, лишь упёршись в 429). Показ ничего не запрещает.

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


def _capped_company_ids(user) -> list:
    """Компании, чей дневной бюджет тратит этот пользователь. Пусто = лимита к нему нет:
    платформенный оператор действует не от имени тенанта, а пользователь без активного
    членства — не тот вектор злоупотребления, ради которого потолок вводился."""
    if getattr(user, "is_platform_admin", False):
        return []
    return list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))


def _used_today(company_ids) -> int:
    """Сколько ИИ-задач компании потратили СЕГОДНЯ (календарный день ``settings.TIME_ZONE``).

    Счёт по всей команде: бюджет платит компания, поэтому в бакет идут задачи каждого активного
    участника, а не только вызывающего. Один индексированный COUNT (список участников уходит
    подзапросом)."""
    # Local imports keep this module free of app-load ordering / circular-import risk.
    from accounts.models import CompanyMember

    from .models import AIJob

    member_user_ids = CompanyMember.objects.filter(
        company_id__in=company_ids,
        is_active=True,
    ).values_list("user_id", flat=True)

    start_of_day = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return AIJob.objects.filter(owner_id__in=member_user_ids, created_at__gte=start_of_day).count()


def ai_daily_usage(user) -> dict:
    """Остаток дневного лимита ИИ для ПОКАЗА: ``{"cap": int|None, "used": int, "remaining": int|None}``.

    Это ИНФОРМАЦИЯ, а не гейт (решение владельца по §7.4 аудита R4): ни одного нового запрета
    здесь нет — потолок как работал в ``enqueue_ai_job``, так и работает. Не хватало ровно того,
    что пользователь узнавал о лимите, лишь упёршись в 429; эталоны (Shopify Magic в подписке,
    Akeneo как add-on) остаток показывают, но подтверждения стоимости перед пачкой не спрашивают.

    ``cap=None`` (и ``remaining=None``) — БЕЗЛИМИТ, отличимый от «0 осталось»: тариф Безлимит,
    отключённый потолок, платформенный оператор, пользователь без компании.

    Потолок тарифа кэшируется на ``AI_DAILY_USAGE_CACHE_TTL`` секунд (его разрешение — это
    запросы к подпискам и энтайтлментам, а ``/me`` дёргается часто); ИЗРАСХОДОВАННОЕ всегда
    считается заново — это то самое число, которое меняется. Кэш живёт ТОЛЬКО в показе:
    ``is_ai_daily_cap_reached`` (предохранитель) резолвит потолок напрямую, чтобы снятие
    лимита оператором действовало на самом деле немедленно.
    """
    company_ids = _capped_company_ids(user)
    if not company_ids:
        return {"cap": None, "used": 0, "remaining": None}

    cap = _cached_cap_for_companies(company_ids)
    used = _used_today(company_ids)
    if cap <= 0:
        return {"cap": None, "used": used, "remaining": None}
    return {"cap": cap, "used": used, "remaining": max(cap - used, 0)}


def _cached_cap_for_companies(company_ids) -> int:
    """Потолок компаний с коротким кэшем — только для ПОКАЗА остатка (см. ``ai_daily_usage``).

    TTL 0/отрицательный отключает кэш (тесты, отладка)."""
    from django.core.cache import cache

    ttl = int(getattr(settings, "AI_DAILY_USAGE_CACHE_TTL", 0) or 0)
    if ttl <= 0:
        return _daily_cap_for_companies(company_ids)
    key = "ai_daily_cap:" + ",".join(str(company_id) for company_id in sorted(company_ids))
    cap = cache.get(key)
    if cap is None:
        cap = _daily_cap_for_companies(company_ids)
        cache.set(key, cap, ttl)
    return cap


def is_ai_daily_cap_reached(user) -> bool:
    """True when the requesting user's company has hit the daily AI-job ceiling.

    Counts today's ``AIJob`` rows owned by any active member of the user's active companies and
    compares against the applicable ceiling, resolved per company as: operator override
    (``CompanyEntitlement(ai.daily_cap).limit``) → subscription-plan tier (Старт/Про/Безлимит) →
    ``AI_DAILY_JOB_CAP_FREE``. Returns False (never capped) for a disabled tier, platform admins,
    and users with no active company membership. Called at the enqueue choke-point.
    """
    company_ids = _capped_company_ids(user)
    if not company_ids:
        return False

    # Предохранитель считает потолок БЕЗ кэша: устаревшее значение здесь либо пропустило бы
    # перерасход, либо продолжило бы запрещать после снятия лимита оператором.
    cap = _daily_cap_for_companies(company_ids)
    if cap <= 0:
        # The applicable tier is disabled (opt-out) — never capped.
        return False

    used_today = _used_today(company_ids)

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
