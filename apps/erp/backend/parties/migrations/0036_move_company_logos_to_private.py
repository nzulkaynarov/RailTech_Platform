"""Data step for 0035: company logos move from the public bucket to the private one (same key).

Idempotent: a key already present in the private storage is not copied again; the public copy is removed only after the
private one exists. Re-running is safe. Reverse copies the files back to the public storage (the field itself is
restored by 0035's reverse)."""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def _storages():
    from core.storage import get_private_storage, get_public_storage

    return get_public_storage(), get_private_storage()


def _transfer(source, target, names) -> dict:
    counts = {"copied": 0, "already": 0, "missing": 0}
    for name in names:
        if target.exists(name):
            counts["already"] += 1
        elif not source.exists(name):
            counts["missing"] += 1
            continue
        else:
            with source.open(name, "rb") as handle:
                target.save(name, handle)
            counts["copied"] += 1
        if source.exists(name):
            source.delete(name)
    return counts


def _logo_names(apps) -> list[str]:
    Company = apps.get_model("parties", "Company")
    return [n for n in Company.objects.exclude(logo="").exclude(logo__isnull=True).values_list("logo", flat=True) if n]


def forward(apps, schema_editor):
    public, private = _storages()
    if public is private:  # one storage in dev/tests without object storage: nothing to move
        return
    counts = _transfer(public, private, _logo_names(apps))
    logger.info("company logos moved to the private storage: %s", counts)


def backward(apps, schema_editor):
    public, private = _storages()
    if public is private:
        return
    counts = _transfer(private, public, _logo_names(apps))
    logger.info("company logos moved back to the public storage: %s", counts)


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0035_company_logo_private"),
    ]

    operations = [migrations.RunPython(forward, backward)]
