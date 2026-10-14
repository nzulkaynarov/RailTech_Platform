from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from core.seeds.delivery_basis import seed_incoterms
from core.seeds.sales import seed_basis_freight, seed_charge_engine
from crm.models import ChargeTemplate, ChargeType

pytestmark = pytest.mark.django_db

_INCOTERMS_MIG = SimpleNamespace(seed_incoterms=seed_incoterms)
_CHARGE_MIG = SimpleNamespace(seed_charge_engine=seed_charge_engine)
_FREIGHT_MIG = SimpleNamespace(seed_basis_freight=seed_basis_freight)


def test_charge_engine_seed_creates_types_and_global_templates():
    # The charge-template profiles reference DeliveryBasis rows, so seed those first
    # (mirrors the migration dependency on master_data 0008).
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)
    _FREIGHT_MIG.seed_basis_freight(django_apps, None)

    assert ChargeType.objects.count() >= 3
    assert ChargeType.objects.filter(code="FREIGHT").exists()

    global_templates = ChargeTemplate.objects.filter(company__isnull=True)
    assert global_templates.exists()
    # DDP is the heaviest profile: freight + insurance + customs + certification.
    ddp_charges = set(global_templates.filter(delivery_basis__code="DDP").values_list("charge_type__code", flat=True))
    assert {"FREIGHT", "INSURANCE", "CERTIFICATION"} <= ddp_charges  # F3.8: freight is a document charge
    assert "CUSTOMS" not in ddp_charges  # customs stays per-line (driven by the line ТНВЭД)


def test_charge_engine_seed_is_idempotent():
    _INCOTERMS_MIG.seed_incoterms(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)
    _CHARGE_MIG.seed_charge_engine(django_apps, None)
    _FREIGHT_MIG.seed_basis_freight(django_apps, None)

    assert ChargeType.objects.filter(code="FREIGHT").count() == 1
    assert (
        ChargeTemplate.objects.filter(
            company__isnull=True, delivery_basis__code="DDP", charge_type__code="INSURANCE"
        ).count()
        == 1
    )
