from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from core.legacy_migration_helpers import dedupe_uom_stubs
from core.seeds.delivery_basis import seed_incoterms
from master_data.models import DeliveryBasis, UnitOfMeasure

pytestmark = pytest.mark.django_db

_MIG = SimpleNamespace(dedupe_uom_stubs=dedupe_uom_stubs)
_INCOTERMS_MIG = SimpleNamespace(seed_incoterms=seed_incoterms)


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


def test_incoterm_basis_seed_creates_full_matrix():
    """B3: a fresh DB must have a working Incoterm responsibility matrix. The data
    migration seeds all 11 terms — DDP makes the seller bear the import customs layer,
    while EXW makes them bear nothing."""
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)

    ddp = DeliveryBasis.objects.get(code="DDP")
    assert ddp.seller_pays_import is True
    assert ddp.seller_pays_freight is True
    assert ddp.seller_pays_delivery is True

    exw = DeliveryBasis.objects.get(code="EXW")
    assert exw.seller_pays_freight is False
    assert exw.seller_pays_import is False

    assert DeliveryBasis.objects.count() >= 11


def test_incoterm_basis_seed_is_idempotent():
    """get_or_create — running the migration twice never errors or duplicates."""
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    assert DeliveryBasis.objects.filter(code="DDP").count() == 1
