"""De-duplicate the catalog taxonomy (Category / EquipmentGroup) — idempotent.

The seed taxonomy got created multiple times historically, so prod had each
top-level category/group ~3× (Category: 103 rows / 29 duplicated names;
EquipmentGroup: 14 / 4) and a typo "Безопастность". Neither model has a unique
constraint on name. The seed command itself is idempotent (get_or_create by name),
so this is a one-time cleanup; it won't re-pollute.

Strategy: merge same-name rows into the lowest-id canonical. CRITICAL: parent is
ON DELETE CASCADE, so children must be re-parented onto the canonical BEFORE the
duplicate is deleted (else they'd cascade-delete). Product.category is SET_NULL and
Product.equipment_groups is M2M — both are remapped onto the canonical to preserve
the links. Reverse is a no-op (a merge can't be undone).
"""

from collections import defaultdict

from django.db import migrations

TYPO_FIXES = {"Безопастность": "Безопасность"}


def _norm(name):
    return (name or "").strip().lower()


def dedupe_taxonomy(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    EquipmentGroup = apps.get_model("catalog", "EquipmentGroup")
    Product = apps.get_model("catalog", "Product")

    # Fix obvious typos first so the corrected row participates in the merge below
    # (and folds into an existing correctly-spelled sibling if one exists).
    for wrong, right in TYPO_FIXES.items():
        Category.objects.filter(name=wrong).update(name=right)
        EquipmentGroup.objects.filter(name=wrong).update(name=right)

    # ── Categories: merge by name; re-parent children + remap products ──
    cat_groups = defaultdict(list)
    for cid, cname in Category.objects.order_by("id").values_list("id", "name"):
        cat_groups[_norm(cname)].append(cid)
    for ids in cat_groups.values():
        if len(ids) < 2:
            continue
        canonical_id, dup_ids = ids[0], ids[1:]
        Category.objects.filter(parent_id__in=dup_ids).update(parent_id=canonical_id)  # re-parent BEFORE delete
        Product.objects.filter(category_id__in=dup_ids).update(category_id=canonical_id)
        Category.objects.filter(id__in=dup_ids).delete()

    # ── EquipmentGroups: merge by name; re-parent children + remap M2M ──
    eg_groups = defaultdict(list)
    for gid, gname in EquipmentGroup.objects.order_by("id").values_list("id", "name"):
        eg_groups[_norm(gname)].append(gid)
    for ids in eg_groups.values():
        if len(ids) < 2:
            continue
        canonical_id, dup_ids = ids[0], ids[1:]
        EquipmentGroup.objects.filter(parent_id__in=dup_ids).update(parent_id=canonical_id)
        canonical = EquipmentGroup.objects.get(id=canonical_id)
        for dup in EquipmentGroup.objects.filter(id__in=dup_ids):
            for product in dup.products.all():
                product.equipment_groups.add(canonical)
        EquipmentGroup.objects.filter(id__in=dup_ids).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_manufacturer_product_brand"),
    ]

    operations = [
        migrations.RunPython(dedupe_taxonomy, reverse_code=noop),
    ]
