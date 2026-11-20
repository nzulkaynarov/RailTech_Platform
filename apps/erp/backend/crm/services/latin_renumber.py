"""One-off Latin renumbering of ERP's own issued numbers and of the copies ERP stores (СЦ-5).

The mapping is one flat `{old number: new number}` shared by all systems. Each system touches ITS OWN tables only:

- `sales_deal.number` — the number of the current stage from the numbering scheme (REQ / PRJ label); deals are found
  by (year, seq), so no previous number is stored;
- `catalog_product.sku` — a random `ТВ-1A2B3C4D` article becomes sequential `GD-00001`, the old one moves to
  `previous_sku` (catalog search matches it);
- copies of numbers of other records: `sales_calctask.letter_number` (EDS letter), `portal_portalnotice.object_number`
  and the exact string values of `portal_portalnotice.params`.

History (bus inbox/outbox, audit and email logs, issued PDFs) is deliberately not touched.
`plan()` is read-only; `apply()` writes everything in one transaction and is idempotent (an already renumbered row no
longer holds an old number, so a second run changes nothing).
"""

import re
from dataclasses import dataclass

from django.db import transaction

# A generated article from before СЦ-5: a non-ASCII (Cyrillic) prefix and eight random hex characters.
_LEGACY_SKU = re.compile(r"^[^\x00-\x7f]+-[0-9A-F]{8}$")
_LATIN_PREFIX = re.compile(r"^[A-Z0-9]{1,10}$")
_SEQ_SKU = re.compile(r"^(?P<prefix>[A-Z0-9]+)-(?P<seq>\d+)$")
_FALLBACK_SKU_PREFIX = {"GENERAL_GOODS": "GD", "SERVICES": "SV"}


@dataclass(frozen=True)
class Change:
    table_column: str
    row_id: int
    old: str
    new: str

    def line(self) -> str:
        return f"{self.table_column} {self.row_id}: {self.old} → {self.new}"


def _sku_prefix(product) -> str:
    domain = product.domain_type
    prefix = getattr(domain, "sku_prefix", "") or ""
    if _LATIN_PREFIX.match(prefix):
        return prefix
    return _FALLBACK_SKU_PREFIX.get(getattr(domain, "code", ""), "SKU")


def emit_mapping() -> dict:
    """ERP's own issued numbers that still do not match the scheme, as `{old: new}` (read-only)."""
    from documents.models import DocumentSequence
    from sales.models import Deal

    from catalog.models import Product
    from crm.services.numbering import own_format_number, type_label

    mapping = {}
    labels = {False: type_label("REQ"), True: type_label("PRJ")}
    for deal in Deal.objects.exclude(number_year__isnull=True).exclude(number_seq__isnull=True).order_by("id"):
        expected = own_format_number(labels[bool(deal.is_project)], deal.number_year, deal.number_seq)
        if deal.number and deal.number != expected:
            mapping[deal.number] = expected

    taken = dict.fromkeys(Product.objects.values_list("sku", flat=True))
    last: dict = {}

    def last_for(prefix: str) -> int:
        if prefix not in last:
            counter = (
                DocumentSequence.objects.filter(company=None, doc_type=f"SKU-{prefix}"[:16], period="ALL")
                .values_list("last_value", flat=True)
                .first()
                or 0
            )
            existing = [int(m["seq"]) for sku in taken if (m := _SEQ_SKU.match(sku)) and m["prefix"] == prefix]
            last[prefix] = max([counter, *existing])
        return last[prefix]

    for product in Product.objects.select_related("domain_type").order_by("id"):
        if not _LEGACY_SKU.match(product.sku or ""):
            continue
        prefix = _sku_prefix(product)
        while True:
            last[prefix] = last_for(prefix) + 1
            candidate = f"{prefix}-{last[prefix]:05d}"
            if candidate not in taken:
                break
        taken[candidate] = None
        mapping[product.sku] = candidate
    return mapping


def _replace_in_json(value, mapping):
    """Exact string values replaced recursively; returns (new value, changed)."""
    if isinstance(value, str):
        return (mapping[value], True) if value in mapping else (value, False)
    if isinstance(value, list):
        out = [_replace_in_json(item, mapping) for item in value]
        return [item for item, _ in out], any(changed for _, changed in out)
    if isinstance(value, dict):
        out = {key: _replace_in_json(item, mapping) for key, item in value.items()}
        return {key: item for key, (item, _) in out.items()}, any(changed for _, changed in out.values())
    return value, False


def plan(mapping: dict) -> list:
    """Every field that would change, without writing anything."""
    from portal.models import PortalNotice
    from sales.models import CalcTask, Deal

    from catalog.models import Product

    changes: list = []
    if not mapping:
        return changes
    olds = list(mapping)
    for deal in Deal.objects.filter(number__in=olds).order_by("id"):
        changes.append(Change("sales_deal.number", deal.id, deal.number, mapping[deal.number]))
    for product in Product.objects.filter(sku__in=olds).order_by("id"):
        changes.append(Change("catalog_product.sku", product.id, product.sku, mapping[product.sku]))
    for task in CalcTask.objects.filter(letter_number__in=olds).order_by("id"):
        changes.append(Change("sales_calctask.letter_number", task.id, task.letter_number, mapping[task.letter_number]))
    for notice in PortalNotice.objects.order_by("id").only("id", "object_number", "params"):
        if notice.object_number in mapping:
            changes.append(
                Change(
                    "portal_portalnotice.object_number", notice.id, notice.object_number, mapping[notice.object_number]
                )
            )
        _, changed = _replace_in_json(notice.params, mapping)
        if changed:
            new_params, _ = _replace_in_json(notice.params, mapping)
            changes.append(Change("portal_portalnotice.params", notice.id, str(notice.params), str(new_params)))
    return changes


@transaction.atomic
def apply(mapping: dict) -> list:
    """Write the plan in ONE transaction; returns the changes made. A second run returns an empty list."""
    from documents.models import DocumentSequence
    from portal.models import PortalNotice
    from sales.models import CalcTask, Deal

    from catalog.models import Product

    changes = plan(mapping)
    if not changes:
        return changes
    olds = list(mapping)
    for deal in Deal.objects.select_for_update().filter(number__in=olds):
        Deal.objects.filter(pk=deal.pk).update(number=mapping[deal.number])
    for product in Product.objects.select_for_update().filter(sku__in=olds):
        new = mapping[product.sku]
        if Product.objects.filter(sku=new).exclude(pk=product.pk).exists():
            raise ValueError(f"article {new} is already taken (mapping for {product.sku})")
        Product.objects.filter(pk=product.pk).update(sku=new, previous_sku=product.previous_sku or product.sku)
        match = _SEQ_SKU.match(new)
        if match:
            doc_type = f"SKU-{match['prefix']}"[:16]
            sequence, _ = DocumentSequence.objects.select_for_update().get_or_create(
                company=None, doc_type=doc_type, period="ALL", defaults={"year": 0}
            )
            if int(match["seq"]) > sequence.last_value:
                sequence.last_value = int(match["seq"])
                sequence.save(update_fields=["last_value"])
    for task in CalcTask.objects.filter(letter_number__in=olds):
        CalcTask.objects.filter(pk=task.pk).update(letter_number=mapping[task.letter_number])
    for notice in PortalNotice.objects.all().only("id", "object_number", "params"):
        fields = {}
        if notice.object_number in mapping:
            fields["object_number"] = mapping[notice.object_number]
        params, changed = _replace_in_json(notice.params, mapping)
        if changed:
            fields["params"] = params
        if fields:
            PortalNotice.objects.filter(pk=notice.pk).update(**fields)
    return changes
