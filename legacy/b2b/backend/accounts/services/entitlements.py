"""Entitlement layer — the monetization keystone (ADR-0006 §3). Rule 8 service.

The app asks `has_entitlement(company_id, FeatureKey.X)` — a stable FEATURE KEY, never a plan name.
A company's plan / promo / demo state is projected into CompanyEntitlement rows; pricing and
packaging changes never touch business code. The free floor (`FREE_FLOOR_FEATURES`) is always
granted so the core loop stays free and the permission engine the КП builder reads is never
circularly paywalled.
"""

from typing import Optional

from django.db import transaction

from ..constants import FREE_FLOOR_FEATURES, SUBSCRIPTION_BASELINE_FEATURES, FeatureKey
from ..models import CompanyEntitlement


def _key(feature_key) -> str:
    """Accept either a FeatureKey enum member or its raw string value."""
    return getattr(feature_key, "value", feature_key)


def _has_operational_subscription(company_id: int) -> bool:
    from ..models import SupplierSubscription

    sub = SupplierSubscription.objects.filter(company_id=company_id).order_by("-updated_at").first()
    return bool(sub and sub.is_operational)


def entitlement_state(company_id: int, feature_key) -> Optional[CompanyEntitlement]:
    """The company's CompanyEntitlement row for this feature (or None). Use when a caller needs the
    nuance — e.g. access == 'DEMO' (watermark/gate output) or the remaining credit balance."""
    if not company_id:
        return None
    return CompanyEntitlement.objects.filter(company_id=company_id, feature_key=_key(feature_key)).first()


def has_entitlement(company_id: int, feature_key) -> bool:
    """True if the company may use `feature_key` right now.

    Free-floor features are always granted. Otherwise an explicit, currently-valid CompanyEntitlement
    row must grant it (access != DISABLED, not expired, credit balance not exhausted). No row → locked.
    """
    key = _key(feature_key)
    if key in FREE_FLOOR_FEATURES:
        return True
    if not company_id:
        return False
    row = CompanyEntitlement.objects.filter(company_id=company_id, feature_key=key).first()
    if row is not None:
        return row.is_currently_granted()  # an explicit grant/revoke/demo ALWAYS wins
    # No explicit row → an operational subscription grants the baseline feature set (so a paying
    # seller is never locked out). Unsubscribed + no row → locked (build is free; send/export aren't).
    return key in SUBSCRIPTION_BASELINE_FEATURES and _has_operational_subscription(company_id)


def is_demo(company_id: int, feature_key) -> bool:
    """True if the company holds this feature in DEMO access (build allowed, output watermarked /
    send+export gated). Free-floor features are never demo."""
    row = entitlement_state(company_id, feature_key)
    return bool(row and row.access == "DEMO" and row.is_currently_granted())


@transaction.atomic
def consume_credit(company_id: int, feature_key, amount: int = 1) -> bool:
    """Atomically spend `amount` credits of a credit-metered feature. Returns False (no change) when
    the feature isn't granted or the balance is insufficient. Features with credits=None (unmetered)
    are always allowed and never decremented."""
    key = _key(feature_key)
    if key in FREE_FLOOR_FEATURES:
        return True
    row = CompanyEntitlement.objects.select_for_update().filter(company_id=company_id, feature_key=key).first()
    if row is None:
        # No explicit row → an operational subscription grants the baseline UNMETERED (mirrors
        # has_entitlement so a subscribed seller isn't blocked just for lacking a credit row).
        return key in SUBSCRIPTION_BASELINE_FEATURES and _has_operational_subscription(company_id)
    if not row.is_currently_granted():
        return False
    if row.credits is None:  # unmetered grant
        return True
    if row.credits < amount:
        return False
    row.credits -= amount
    row.save(update_fields=["credits", "updated_at"])
    return True


@transaction.atomic
def grant_entitlement(
    company_id: int,
    feature_key,
    *,
    access: str = "ENABLED",
    limit: Optional[int] = None,
    credits: Optional[int] = None,
    expires_at=None,
    note: str = "",
) -> CompanyEntitlement:
    """Upsert a company's entitlement for a feature (billing / admin / promo projection)."""
    row, _created = CompanyEntitlement.objects.update_or_create(
        company_id=company_id,
        feature_key=_key(feature_key),
        defaults={"access": access, "limit": limit, "credits": credits, "expires_at": expires_at, "note": note},
    )
    return row


def quote_send_entitled(company_id: int) -> bool:
    """May this seller company SEND a КП (Quote) to the client? Requires all of:
      1. KYC-verified (L2+) — «без KYC только демо»: an unverified seller may build a КП and see a
         watermarked preview, but never send a real one (the seller half of the ADR-0006 KYC floor);
      2. the quote.send entitlement — an operational subscription grants it;
      3. NOT a DEMO grant (demo = build + watermark, but not actually send).
    Distinct from can_send_quote_to_client (the role-PERMISSION check) — this is the KYC+billing gate."""
    from .kyc import company_kyc_verified

    return (
        company_kyc_verified(company_id)
        and has_entitlement(company_id, FeatureKey.QUOTE_SEND)
        and not is_demo(company_id, FeatureKey.QUOTE_SEND)
    )


def quote_export_entitled(company_id: int) -> bool:
    """May this seller company EXPORT a КП (Quote, PDF/Excel cost data)? Same KYC + paid-output gate
    as send — an unverified seller stays in demo (no commercial export)."""
    from .kyc import company_kyc_verified

    return (
        company_kyc_verified(company_id)
        and has_entitlement(company_id, FeatureKey.QUOTE_EXPORT)
        and not is_demo(company_id, FeatureKey.QUOTE_EXPORT)
    )
