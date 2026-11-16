"""Миграция catalog/0016 (ADR-0027): строки КП без карточки получают карточку, откат снимает созданные ею черновики.

Функции миграции вызываются на текущих моделях (их API для миграции тот же); данные — как на проде 2026-11-17: строки
КП без карточки, товар и услуга, два совпадающих названия.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from django.test import override_settings

from catalog.models import DomainType, Product
from catalog.tests.test_candidates import _line, world  # noqa: F401  # мир продавца и КП
from sales.models import CalcLine, CalcLineKind

pytestmark = pytest.mark.django_db

migration = importlib.import_module("catalog.migrations.0016_link_quote_lines_to_cards")


def test_lines_get_cards_and_rollback_removes_them(world):  # noqa: F811
    quote = world["quote"]
    rails = _line(quote, imported_raw_name="рельсы")
    same = _line(quote, position=2, imported_raw_name="Рельсы")
    service = _line(quote, position=3, imported_raw_name="логисика")
    CalcLine.objects.create(item=service, kind=CalcLineKind.SERVICE)
    section = _line(quote, position=4, imported_raw_name="Раздел", display_type="SECTION")

    with override_settings(OWN_COMPANY_ID=world["seller"].pk):
        migration.forwards(apps, None)

    for line in (rails, same, service, section):
        line.refresh_from_db()
    assert rails.product_id and rails.product_id == same.product_id
    assert Product.objects.get(pk=rails.product_id).demand_count == 2
    assert Product.objects.get(pk=service.product_id).domain_type.code == DomainType.SERVICES
    assert section.product_id is None
    assert rails.product.owner_company_id == world["seller"].pk and rails.product.status.code == "DRAFT"

    migration.backwards(apps, None)
    service.refresh_from_db()
    assert service.product_id is None
    assert not Product.objects.filter(name="логисика").exists()
