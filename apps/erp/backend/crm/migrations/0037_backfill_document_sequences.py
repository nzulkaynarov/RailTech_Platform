"""Backfill DocumentSequence counters from existing document numbers.

0020 created DocumentSequence but never seeded last_value, so on a DB that already
had Contracts/Invoices/Acts the counter started at 0 and re-issued numbers that
already existed → `duplicate key ... _number_key` 500 in prod. This raises each
(doc_type, year) counter to the max existing suffix. Idempotent; reverse = no-op.
"""

import re

from django.db import migrations

# (doc_type, prefix, model_name) — the three sequence-numbered documents.
_DOCS = [("CT", "CT", "Contract"), ("INV", "INV", "Invoice"), ("ACT", "ACT", "Act")]
_PAT = re.compile(r"^([A-Z]+)-(\d{4})-(\d+)$")


def backfill_sequences(apps, schema_editor):
    DocumentSequence = apps.get_model("crm", "DocumentSequence")
    for doc_type, prefix, model_name in _DOCS:
        Model = apps.get_model("crm", model_name)
        max_by_year = {}
        for number in Model.objects.values_list("number", flat=True):
            match = _PAT.match((number or "").strip())
            if not match or match.group(1) != prefix:
                continue
            year, suffix = int(match.group(2)), int(match.group(3))
            if suffix > max_by_year.get(year, 0):
                max_by_year[year] = suffix
        for year, max_suffix in max_by_year.items():
            seq = DocumentSequence.objects.get_or_create(doc_type=doc_type, year=year, defaults={"last_value": 0})[0]
            if seq.last_value < max_suffix:
                seq.last_value = max_suffix
                seq.save(update_fields=["last_value"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("crm", "0036_seed_charge_engine")]
    operations = [migrations.RunPython(backfill_sequences, noop)]
