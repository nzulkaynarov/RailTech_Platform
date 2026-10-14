"""Per-company daily AI-job spend cap (security audit #13).

The 8 interactive AI features all funnel through ``enqueue_ai_job`` (ARCH-01);
each enqueued job is a paid Anthropic call. Without a ceiling a runaway script or
an abusive tenant could run an unbounded bill. This module answers ONE question —
"has the requesting user's company already used its daily quota?" — so the
enqueue choke-point can refuse with a 429 BEFORE queuing the task or spending a
request. The same numbers answer a second, purely informational question —
"сколько осталось на сегодня?" (``ai_daily_usage``) — которую ``/me`` показывает в
интерфейсе: аудит R4 §7.4, механизм был, не хватало ВИДИМОСТИ (пользователь узнавал
о лимите, лишь упёршись в 429). Показ ничего не запрещает.

Design notes (a safety fuse, not a product tier):
- ONE ceiling for every company: ``settings.AI_DAILY_JOB_CAP_PER_COMPANY``. Тарифы подписки
  (Старт/Про/Безлимит), «бесплатный» потолок и операторский override по компании
  удалены вместе с монетизацией платформы (M1-ERP-02 волна 2): продавец в ансамбле один.
- The count comes straight from the persistent ``AIJob`` rows (no new Redis/DB
  state, no extra infra to keep consistent). One indexed COUNT per enqueue.
- Scope is the CALENDAR DAY in ``settings.TIME_ZONE`` and the requesting user's
  active company (the whole team shares one bucket — the bill is per company).
- Exempt (never capped): the cap disabled (<= 0), the administrator (does not act on
  behalf of a company), and users with no active company membership.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _daily_cap() -> int:
    """The daily ceiling of one company: 0/negative = UNLIMITED (opt-out)."""
    return getattr(settings, "AI_DAILY_JOB_CAP_PER_COMPANY", 0)


def _capped_company_ids(user) -> list:
    """Компании, чей дневной бюджет тратит этот пользователь. Пусто = лимита к нему нет:
    платформенный оператор действует не от имени тенанта, а пользователь без активного
    членства — не тот вектор злоупотребления, ради которого потолок вводился."""
    if getattr(user, "is_superuser", False):
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

    ``cap=None`` (и ``remaining=None``) — БЕЗЛИМИТ, отличимый от «0 осталось»: отключённый
    потолок, администратор, пользователь без компании.

    Потолок — настройка (``AI_DAILY_JOB_CAP_PER_COMPANY``); израсходованное считается заново
    на каждый вызов.
    """
    company_ids = _capped_company_ids(user)
    if not company_ids:
        return {"cap": None, "used": 0, "remaining": None}

    cap = _daily_cap()
    used = _used_today(company_ids)
    if cap <= 0:
        return {"cap": None, "used": used, "remaining": None}
    return {"cap": cap, "used": used, "remaining": max(cap - used, 0)}


def is_ai_daily_cap_reached(user) -> bool:
    """True when the requesting user's company has hit the daily AI-job ceiling.

    Counts today's ``AIJob`` rows owned by any active member of the user's active companies and
    compares against ``AI_DAILY_JOB_CAP_PER_COMPANY``. Returns False (never capped) for a disabled
    cap, the administrator, and users with no active company membership. Called at the enqueue
    choke-point.
    """
    company_ids = _capped_company_ids(user)
    if not company_ids:
        return False

    cap = _daily_cap()
    if cap <= 0:
        # The cap is disabled (opt-out) — never capped.
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
