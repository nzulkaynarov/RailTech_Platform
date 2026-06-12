from dataclasses import dataclass
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# Parameter dataclasses — reduce long argument lists (Sprint 4b).
# ──────────────────────────────────────────────────────────────────────────


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
