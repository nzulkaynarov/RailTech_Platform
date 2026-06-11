import importlib

import pytest
from django.apps import apps as django_apps

from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db

_MIG = importlib.import_module("master_data.migrations.0004_dedupe_uom_stubs")


def test_dedupe_removes_cyrillic_uom_stub_keeps_latin():
    """0004: the Cyrillic-code UoM duplicate (шт) is removed; the canonical Latin
    code (PCS) stays — both share the display name 'Штука'."""
    UnitOfMeasure.objects.create(code="PCS", name="Штука", sort_order=1)
    UnitOfMeasure.objects.create(code="шт", name="Штука", sort_order=2)

    _MIG.dedupe_uom_stubs(django_apps, None)

    assert not UnitOfMeasure.objects.filter(code="шт").exists()
    assert UnitOfMeasure.objects.filter(code="PCS").exists()


def test_dedupe_uom_is_idempotent_and_safe_without_stub():
    """No stub present → no-op; running twice never errors."""
    UnitOfMeasure.objects.create(code="KG", name="Килограмм", sort_order=1)
    _MIG.dedupe_uom_stubs(django_apps, None)
    _MIG.dedupe_uom_stubs(django_apps, None)
    assert UnitOfMeasure.objects.filter(code="KG").exists()
