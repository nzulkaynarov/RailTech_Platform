"""Who must sign in with a second factor (DV-4b, risk register D1).

The rule is derived from the permission sections an employee effectively holds (the union of all
his roles, `merge_access`) and never from role names. One config place below: sections with money
and access. Later this tuple becomes an admin-editable setting (processes-as-data); the function
stays the single point that answers "is the factor mandatory for this access".
"""

from collections.abc import Mapping
from typing import Final

# (catalog section, minimal level). `full` only: reading payments or drafts is not money or access.
FACTOR_REQUIRED_SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("eds.payments", "full"),  # pay and confirm bank details
    ("eds.memo.approve", "full"),  # approve memos
    ("eds.drafts", "full"),  # approvals of outgoing documents
    ("admin", "full"),  # settings and roles
)

_RANK: Final = {"read": 1, "full": 2}


def required_sections(access: Mapping[str, str]) -> list[str]:
    """Sections of the effective access that make the second factor mandatory (catalog order)."""
    return [
        section
        for section, level in FACTOR_REQUIRED_SECTIONS
        if _RANK.get(access.get(section, ""), 0) >= _RANK[level]
    ]


def factor_required(access: Mapping[str, str], *, is_active: bool = True) -> bool:
    """True when the effective access holds any section with money or access."""
    return is_active and bool(required_sections(access))
