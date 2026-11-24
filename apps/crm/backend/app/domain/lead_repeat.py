"""Repeat requests and possible duplicates of a lead (PL-3). Pure functions, no I/O.

A person writes again from the site (or shares the phone in the bot) and is matched to an existing
lead. The existing card keeps its values; what the repeat brings is not lost:

- an empty company is filled; an e-mail or phone is NEVER written by an anonymous request (the
  matched channel is stored, the other one is unverified);
- a new e-mail/phone or a differing value goes to the note and to the structured fact
  `qualification["repeat_requests"]` (`new_contacts`, `unverified`) for a manager to apply;
- origin facts (form, page, referrer, UTM, landing language) and the consent version of the
  repeat are recorded in the same fact.

`qualification["possible_duplicates"]` holds suggestions (an e-mail or phone that belongs to a
client contact but could not be attached safely); nothing is merged on their basis.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

REPEAT_KEY: Final = "repeat_requests"
DUPLICATES_KEY: Final = "possible_duplicates"
FACTS_MAX: Final = 20
CONTACT_FIELDS: Final = ("email", "phone_e164", "company_name")
FILLABLE_FIELDS: Final = ("company_name",)
# Forms of the site for people who are not buyers: a request from them is not a customer's repeat.
_NON_CUSTOMER_MARKS: Final = ("partner", "supplier", "vendor", "carrier", "career", "job")


@dataclass(frozen=True, slots=True)
class ContactMerge:
    """Result of comparing the stored contacts of a lead with the ones of a repeat request."""

    filled: dict[str, str] = field(default_factory=dict)
    differing: dict[str, str] = field(default_factory=dict)


def compare_contacts(
    stored: Mapping[str, str | None], incoming: Mapping[str, str | None]
) -> ContactMerge:
    """What the repeat request brings: `filled` (only the company, when empty) and `differing`.

    The anonymous form is not proof of owning the e-mail or phone it carries: the channel that
    matched the lead is already stored, the other one is unverified. So a new e-mail or phone is
    never `filled`; it is `differing` (to be applied by a manager). An empty company is filled.
    """
    filled: dict[str, str] = {}
    differing: dict[str, str] = {}
    for name in CONTACT_FIELDS:
        new = (incoming.get(name) or "").strip()
        if not new:
            continue
        old = (stored.get(name) or "").strip()
        if not old and name in FILLABLE_FIELDS:
            filled[name] = new
        elif not old or old.casefold() != new.casefold():
            differing[name] = new
    return ContactMerge(filled, differing)


def is_customer_form(form: str | None) -> bool:
    """The request is from a buyer (the default) and not from a partner, supplier or a candidate."""
    key = (form or "").lower()
    return not any(mark in key for mark in _NON_CUSTOMER_MARKS)


def append_fact(
    qualification: Mapping[str, Any], key: str, entry: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """New qualification dict with `entry` appended to the list under `key` (last FACTS_MAX)."""
    items = [*(qualification.get(key) or []), {"at": now.isoformat(), **entry}]
    return {**qualification, key: items[-FACTS_MAX:]}
