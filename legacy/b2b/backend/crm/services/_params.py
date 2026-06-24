from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from accounts.models import CustomUser

# ──────────────────────────────────────────────────────────────────────────
# Parameter dataclasses — reduce long argument lists (Sprint 4b).
# ──────────────────────────────────────────────────────────────────────────


def has_explicit_company_role_perm(user: "CustomUser", company_id: int, perm: str) -> bool:
    """True only when the member has an explicit CompanyRole that grants `perm`.

    Unlike accounts.services.permissions.member_has_permission() this skips the
    legacy can_sell/can_buy fallback, so it fires only for members intentionally
    assigned a named role with a specific permission set — not for every member
    whose default capability flag happens to map to the permission.

    Used as the additive defense-in-depth layer alongside the existing WorkspaceRole
    / capability guards: the new check expands access for explicitly-granted roles
    without silently promoting all legacy members.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    membership = (
        user.memberships.filter(company_id=company_id, is_active=True)
        .select_related("company_role")
        .first()
    )
    if membership is None or not membership.company_role_id:
        return False
    return membership.company_role.has_perm(perm)


@dataclass
class PaymentData:
    """Groups payment-related parameters for record_payment()."""

    invoice_id: int
    amount: object  # Decimal-coercible (str, int, float, Decimal)
    paid_at: object  # date or datetime
    method: str = "BANK_TRANSFER"
    reference: str = ""
    proof_file: Optional[object] = None
    manual: bool = True
