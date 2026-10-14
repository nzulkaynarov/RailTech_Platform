"""«КП vs заявка»: доступ к сверке. Сама сверка (детерминированная часть и ИИ) — в
``ai.services.quote_diff`` (M1-ERP-06); здесь — граница доступа и переходный ре-экспорт."""

from __future__ import annotations

from ai.services.quote_diff import (  # noqa: F401 — переходный ре-экспорт (DECISIONS 2026-10-14)
    ISSUE_NOTE_IGNORED,
    ISSUE_QTY_UNIT,
    ISSUE_SUBSTITUTED,
    ISSUE_UNCOVERED,
    MAX_DIFF_LINES,
    quote_vs_request_diff,
)

from accounts.models import CustomUser

from ..models import Quote


def user_can_view_quote_diff(user: CustomUser, quote: Quote) -> bool:
    """Scope guard (Rule: only the deal's buyer or the own company's staff). The diff is
    assistive read-only, so a platform admin viewer may also inspect it. Buyer =
    the deal's client OR an active member of the deal's company; seller = staff of the
    own company (the single seller). Reuses the accounts permission helpers — no bespoke
    membership logic here.
    """
    from accounts.services.permissions import is_seller

    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    deal = quote.deal
    # Buyer side: the deal's contact user, or any active member of the buyer company.
    if deal.client_id == user.id:
        return True
    if deal.company_id and user.memberships.filter(company_id=deal.company_id, is_active=True).exists():
        return True
    # Seller side: staff of the own company.
    return is_seller(user)
