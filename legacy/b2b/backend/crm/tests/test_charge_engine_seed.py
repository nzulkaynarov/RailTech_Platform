import importlib

import pytest
from django.apps import apps as django_apps

from crm.models import ChargeTemplate, ChargeType

pytestmark = pytest.mark.django_db

# B3: the КП charge engine's reference data moved out of core_seed (a demo seeder)
# into idempotent data migrations. These tests assert that running those migrations
# on a DB yields a working charge apparatus (≥3 ChargeType rows + ≥1 GLOBAL template).
_INCOTERMS_MIG = importlib.import_module("master_data.migrations.0008_seed_delivery_basis_incoterms")
_CHARGE_MIG = importlib.import_module("crm.migrations.0036_seed_charge_engine")


def test_charge_engine_seed_creates_types_and_global_templates():
    # The charge-template profiles reference DeliveryBasis rows, so seed those first
    # (mirrors the migration dependency on master_data 0008).
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)

    assert ChargeType.objects.count() >= 3
    assert ChargeType.objects.filter(code="FREIGHT").exists()

    global_templates = ChargeTemplate.objects.filter(company__isnull=True)
    assert global_templates.exists()
    # DDP is the heaviest profile: freight + insurance + customs + certification.
    ddp_charges = set(
        global_templates.filter(delivery_basis__code="DDP").values_list("charge_type__code", flat=True)
    )
    assert {"FREIGHT", "INSURANCE", "CUSTOMS", "CERTIFICATION"} <= ddp_charges


def test_charge_engine_seed_is_idempotent():
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)

    assert ChargeType.objects.filter(code="FREIGHT").count() == 1
    assert (
        ChargeTemplate.objects.filter(
            company__isnull=True, delivery_basis__code="DDP", charge_type__code="FREIGHT"
        ).count()
        == 1
    )
