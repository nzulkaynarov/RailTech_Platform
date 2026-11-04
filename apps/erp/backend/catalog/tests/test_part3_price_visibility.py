"""PART-3: цены партнёра в каталоге — «показывать / по запросу» по договорённости; порядок уровней карточка → партнёр → компания.

Цену-витрину задаёт сама карточка (`Product.list_price`), предложение партнёра для витрины не выбирается: партнёр карточки —
её источник данных (`Product.source_supplier`). Клиент видит ту же проекцию, что отдаёт портал (`catalog.published`).
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from parties.models import CompanyRelationship, CompanySettings, RelationshipRole, RelationshipStatus

from accounts.models import Company
from accounts.testing import make_own_company
from catalog.completeness import completeness
from catalog.constants import MODE_CLIENT, PriceVisibility
from catalog.models import Product, ProductStatus
from catalog.policy import effective_price_visibility, price_visibility_source
from catalog.published import project, project_many
from core.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

CABINET, ON_REQUEST = PriceVisibility.CABINET.value, PriceVisibility.ON_REQUEST.value


@pytest.fixture
def world():
    own = make_own_company(Company.objects.create(name="Своя компания", inn="400000001"))
    partner = Company.objects.create(name="Завод Север", inn="400000002")
    relation = CompanyRelationship.objects.create(
        company=partner, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
    )
    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сум", "sort_order": 2})[0]
    unit = UnitOfMeasure.objects.get_or_create(code="pcs", defaults={"name": "шт", "sort_order": 1})[0]
    published = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликована"})[0]

    def card(name="Болт А-1", **extra):
        return Product.objects.create(
            name=name,
            owner_company=own,
            source_supplier=extra.pop("source_supplier", partner),
            status=published,
            uom=unit,
            list_price=Decimal("12500.00"),
            list_price_currency=uzs,
            **extra,
        )

    def company_policy(value):
        CompanySettings.objects.update_or_create(company=own, defaults={"catalog_price_visibility": value})

    def agreement(value):
        relation.catalog_price_visibility = value
        relation.save()

    return {
        "own": own,
        "partner": partner,
        "relation": relation,
        "card": card,
        "company": company_policy,
        "deal": agreement,
    }


class TestOrderOfLevels:
    def test_without_anything_the_product_default_is_on_request(self, world):
        assert effective_price_visibility(world["card"]()) == ON_REQUEST

    def test_company_policy_applies_when_the_partner_has_no_agreement(self, world):
        world["company"](CABINET)
        card = world["card"]()
        assert price_visibility_source(card) == (CABINET, "company")

    def test_partner_agreement_beats_company_policy_both_ways(self, world):
        world["company"](ON_REQUEST)
        world["deal"](CABINET)
        card = world["card"]()
        assert price_visibility_source(card) == (CABINET, "partner")
        world["company"](CABINET)
        world["deal"](ON_REQUEST)
        assert price_visibility_source(card) == (ON_REQUEST, "partner")

    def test_own_card_policy_beats_partner_agreement(self, world):
        world["deal"](ON_REQUEST)
        card = world["card"](price_visibility=CABINET)
        assert price_visibility_source(card) == (CABINET, "item")

    def test_empty_agreement_means_as_company(self, world):
        world["company"](CABINET)
        world["deal"]("")
        assert price_visibility_source(world["card"]()) == (CABINET, "company")

    def test_card_without_a_source_supplier_follows_the_company(self, world):
        world["company"](CABINET)
        assert price_visibility_source(world["card"](source_supplier=None)) == (CABINET, "company")

    def test_agreement_of_another_partner_is_not_applied(self, world):
        world["deal"](CABINET)
        other = Company.objects.create(name="Завод Юг", inn="400000003")
        CompanyRelationship.objects.create(
            company=other, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
        )
        assert price_visibility_source(world["card"](source_supplier=other)) == (ON_REQUEST, "company")

    def test_client_relationship_row_is_not_a_price_agreement(self, world):
        """Отношение «клиент» той же компании цен каталога не задаёт: договорённость — только у роли «партнёр»."""
        world["relation"].delete()
        CompanyRelationship.objects.create(
            company=world["partner"],
            role=RelationshipRole.CLIENT,
            status=RelationshipStatus.ACTIVE,
            catalog_price_visibility=CABINET,
        )
        assert price_visibility_source(world["card"]()) == (ON_REQUEST, "company")


class TestClientSeesTheAgreement:
    def test_price_is_shown_or_hidden_by_the_agreement(self, world):
        card = world["card"]()
        assert project(card, mode=MODE_CLIENT)["price"] is None
        world["deal"](CABINET)
        assert project(card, mode=MODE_CLIENT)["price"] == {"amount": "12500.00", "currency": "UZS"}
        world["company"](CABINET)
        world["deal"](ON_REQUEST)
        assert project(card, mode=MODE_CLIENT)["price"] is None

    def test_batch_projection_uses_the_agreement_without_a_query_per_card(self, world):
        from catalog.published import published_products

        world["deal"](CABINET)
        for i in range(3):
            world["card"](f"Болт {i}")
        with CaptureQueriesContext(connection) as few:
            rows = project_many(list(published_products()), mode=MODE_CLIENT)
        assert all(row["price"] == {"amount": "12500.00", "currency": "UZS"} for row in rows)
        for i in range(12):
            world["card"](f"Гайка {i}")
        with CaptureQueriesContext(connection) as many:
            project_many(list(published_products()), mode=MODE_CLIENT)
        assert len(many) == len(few)


class TestPublishNeedsAPriceWhenItWillBeShown:
    def test_showing_partner_requires_the_list_price(self, world):
        card = world["card"]()
        card.list_price = None
        card.save()
        assert "list_price" not in [m["code"] for m in completeness(card)["missing"]]
        world["deal"](CABINET)
        assert "list_price" in [m["code"] for m in completeness(card)["missing"]]


class TestSuspendedRelationship:
    def test_agreement_keeps_working_while_the_cabinet_access_is_suspended(self, world):
        """Договорённость о ценах товаров партнёра не исчезает от приостановки его входа в кабинет."""
        world["deal"](CABINET)
        world["relation"].status = RelationshipStatus.SUSPENDED
        world["relation"].save()
        assert price_visibility_source(world["card"]()) == (CABINET, "partner")
