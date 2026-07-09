"""
Admin audit helper.

Centralized writer for ActivityLog entries produced by admin/override actions.
Populates the entity scope (entity_type, entity_id), a reason, and optional
before/after JSON snapshots so the Timeline tab on admin detail pages can
render a diff.

Usage:
    from core.audit import log_admin_action
    log_admin_action(
        entity_type='company', entity_id=company.id,
        action='KYC approved to L2',
        detail=f'{company.name}: PROFILE_SUBMITTED → L2_VERIFIED',
        actor=request.user, reason=reason,
        before={'verification_status': 'PROFILE_SUBMITTED'},
        after={'verification_status': 'L2_VERIFIED'},
    )
"""

from __future__ import annotations

from typing import Any, Optional


def log_admin_action(
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    detail: str = "",
    actor=None,
    reason: str = "",
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    level: str = "INFO",
    expires_at=None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    seller_company_id: Optional[int] = None,
):
    """
    Create an ActivityLog entry scoped to a single entity.

    All admin override actions must route through this helper so the timeline
    remains consistent. `expires_at` time-boxes a break-glass access grant (G2).
    company_id/contact_id/deal_id link the entry into the CRM counterparty
    timeline (Phase A, spec-remaining-2026-07-07 §2.1) — call sites pass
    whatever counterparty scope they have in context.
    """
    from crm.models import ActivityLog

    # SEC (audit #4): tag the seller lane so the «История» feed scopes per-lane. If not given
    # explicitly, derive it from a seller actor's routed company on this deal — a buyer/system
    # actor stays NULL (deal-level event, visible to all parties). One place auto-tags every
    # seller-authored deal event (КП sent/accepted, stage, chat) without touching each caller.
    if seller_company_id is None and deal_id and actor is not None:
        from accounts.services.permissions import routed_seller_company_id

        seller_company_id = routed_seller_company_id(actor, deal_id)

    return ActivityLog.objects.create(
        action=action[:255],
        detail=detail,
        user=actor,
        level=level,
        entity_type=entity_type[:40],
        entity_id=int(entity_id) if entity_id else None,
        reason=(reason or "")[:5000],
        before_data=before,
        after_data=after,
        expires_at=expires_at,
        company_id=company_id,
        contact_id=contact_id,
        deal_id=deal_id,
        seller_company_id=seller_company_id,
    )
