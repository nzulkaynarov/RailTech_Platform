"""M1-ERP-07 — единая карточка «товар / услуга», порог публикации и политика видимости.

Эталон: Odoo `product.template` (вид consu/service, политика выставления услуги fixed / milestones /
timesheets, `is_published`) + Akeneo completeness (порог считает код, интерфейс называет недостающее).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.completeness import completeness
from catalog.models import Category, DomainType, Product, ProductImage, ProductStatus
from catalog.publishing import publish_blockers, publish_product, set_visibility
from catalog.services import publish_products
from master_data.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"


@pytest.fixture
def world(db, grant):
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    own = Company.objects.create(name="Своя компания P", inn="420000001")
    own.types.add(supplier_type)

    def member(email, *codes):
        user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
        CompanyMember.objects.create(
            user=user, company=own, role=WorkspaceRole.objects.get(code="MEMBER"), is_primary=True, is_active=True
        )
        grant(user, *codes)
        return user

    goods = DomainType.objects.get(code=DomainType.GENERAL_GOODS)
    services = DomainType.objects.get(code=DomainType.SERVICES)
    return {
        "own": own,
        "publisher": member("publisher@own.example", "catalog.manage", "catalog.publish"),
        "editor": member("editor@own.example", "catalog.manage"),
        "goods": goods,
        "services": services,
        "goods_category": Category.objects.filter(domain_type=goods).first(),
        "services_category": Category.objects.filter(domain_type=services).first(),
        "pcs": UnitOfMeasure.objects.get(code="H87"),
        "hour": UnitOfMeasure.objects.get(code="HUR"),
        "uzs": Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сум"})[0],
    }


def _goods(world, **overrides):
    fields = {
        "name": "Кабель ВВГ 3×2,5",
        "description": "Медный, в двойной изоляции",
        "domain_type": world["goods"],
        "category": world["goods_category"],
        "uom": world["pcs"],
        "hs_code": "8544492000",
        "owner_company": world["own"],
    }
    fields.update(overrides)
    return Product.objects.create(**fields)


def _service(world, **overrides):
    fields = {
        "name": "Монтаж щита",
        "description": "Монтаж и подключение на объекте",
        "domain_type": world["services"],
        "category": world["services_category"],
        "uom": world["hour"],
        "fulfillment_policy": "time",
        "owner_company": world["own"],
    }
    fields.update(overrides)
    return Product.objects.create(**fields)


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# ── Вид и политика исполнения ────────────────────────────────────────────────────────────


def test_kind_follows_the_domain_type(world):
    assert _goods(world).kind == "goods"
    assert _service(world).kind == "service"
    assert Product.objects.create(name="Кандидат", owner_company=world["own"]).kind is None


def test_goods_carry_no_fulfillment_policy(world):
    card = _goods(world, fulfillment_policy="milestones")

    card.refresh_from_db()
    assert card.fulfillment_policy == ""


@pytest.mark.parametrize(
    "overrides, expected_missing",
    [
        ({}, []),
        ({"fulfillment_policy": ""}, ["fulfillment_policy"]),
        ({"uom": "pcs"}, ["time_unit"]),
        ({"uom": "pcs", "fulfillment_policy": "fixed"}, []),
        ({"uom": "pcs", "fulfillment_policy": "milestones"}, []),
        ({"description": "", "specifications": {"Выезд": "в пределах города"}}, []),
        ({"description": "", "specifications": {"Выезд": ""}}, ["content"]),
        ({"category": None}, ["category"]),
    ],
)
def test_service_threshold(world, overrides, expected_missing):
    if overrides.get("uom") == "pcs":
        overrides = {**overrides, "uom": world["pcs"]}
    card = _service(world, **overrides)

    assert publish_blockers(card) == expected_missing


@pytest.mark.parametrize(
    "overrides, visibility, expected_missing",
    [
        ({}, "on_request", []),
        ({}, "cabinet", ["list_price"]),
        ({"list_price": Decimal("10.00")}, "cabinet", ["list_price"]),
        ({"list_price": Decimal("10.00"), "currency": True}, "cabinet", []),
        ({"description": ""}, "on_request", ["content"]),
        ({"hs_code": ""}, "on_request", ["hs_code"]),
        ({"domain_type": None, "hs_code": ""}, "on_request", ["kind", "hs_code"]),
    ],
)
def test_goods_threshold_depends_on_visibility(world, overrides, visibility, expected_missing):
    overrides = dict(overrides)
    if overrides.pop("currency", False):
        overrides["list_price_currency"] = world["uzs"]
    card = _goods(world, **overrides)

    assert publish_blockers(card, visibility) == expected_missing
    assert completeness(card, visibility=visibility)["is_publishable"] is (not expected_missing)


# ── Публикация и видимость: API ─────────────────────────────────────────────────────────


def test_publish_incomplete_answers_with_the_missing_list(world):
    card = _goods(world, description="", category=None)

    response = _api(world["publisher"]).post(f"{PRODUCTS_URL}{card.pk}/publish/", {}, format="json")

    assert response.status_code == 400
    assert response.json() == {"detail": "CATALOG_PUBLISH_INCOMPLETE", "missing": ["category", "content"]}
    card.refresh_from_db()
    assert card.status.code == "DRAFT"


def test_publish_with_cabinet_visibility_requires_the_client_price(world):
    card = _goods(world)
    client = _api(world["publisher"])

    refused = client.post(f"{PRODUCTS_URL}{card.pk}/publish/", {"visibility": "cabinet"}, format="json")
    assert refused.json() == {"detail": "CATALOG_PUBLISH_INCOMPLETE", "missing": ["list_price"]}

    card.list_price, card.list_price_currency = Decimal("12500.00"), world["uzs"]
    card.save()
    published = client.post(f"{PRODUCTS_URL}{card.pk}/publish/", {"visibility": "cabinet"}, format="json")

    assert published.status_code == 200, published.content
    assert published.json()["status_code"] == "PUBLISHED"
    assert published.json()["visibility"] == "cabinet"
    assert published.json()["client_preview"]["price"] == {"amount": "12500.00", "currency": "UZS"}


def test_default_visibility_is_on_request(world):
    card = _goods(world)

    assert card.visibility == "on_request"
    publish_product(card, world["publisher"])
    card.refresh_from_db()
    assert card.status.code == "PUBLISHED" and card.visibility == "on_request"


def test_visibility_of_a_published_card_passes_the_threshold(world):
    card = _goods(world)
    publish_product(card, world["publisher"])
    client = _api(world["publisher"])

    refused = client.post(f"{PRODUCTS_URL}{card.pk}/visibility/", {"visibility": "cabinet"}, format="json")
    assert refused.status_code == 400
    assert refused.json()["missing"] == ["list_price"]

    invalid = client.post(f"{PRODUCTS_URL}{card.pk}/visibility/", {"visibility": "everyone"}, format="json")
    assert invalid.json() == {"detail": "CATALOG_VISIBILITY_INVALID"}


def test_visibility_of_a_draft_is_remembered_until_publication(world):
    card = _goods(world)

    updated, error = set_visibility(card, world["publisher"], "cabinet")

    assert error is None and updated.visibility == "cabinet"
    assert publish_blockers(updated) == ["list_price"], "публиковать «в кабинете» без цены нельзя"


def test_visibility_is_not_writable_through_the_form(world):
    """Показ цены клиенту — решение `catalog.publish`, а не правка формы под `catalog.manage`."""
    card = _goods(world)

    response = _api(world["editor"]).patch(f"{PRODUCTS_URL}{card.pk}/", {"visibility": "cabinet"}, format="json")

    assert response.status_code == 200
    card.refresh_from_db()
    assert card.visibility == "on_request"


def test_editor_without_publish_right_cannot_change_visibility(world):
    card = _goods(world)

    response = _api(world["editor"]).post(f"{PRODUCTS_URL}{card.pk}/visibility/", {"visibility": "cabinet"})

    assert response.status_code == 403
    assert response.json() == {"detail": "ROLE_NOT_PERMITTED"}


def test_form_writes_the_published_layer_fields(world):
    card = _service(world)

    response = _api(world["editor"]).patch(
        f"{PRODUCTS_URL}{card.pk}/",
        {
            "fulfillment_policy": "milestones",
            "list_price": "300000.00",
            "list_price_currency": world["uzs"].pk,
            "client_lead_time_days": 7,
            "internal_notes": "Субподрядчик — только по договору",
        },
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["kind"] == "service"
    assert body["fulfillment_policy"] == "milestones"
    assert body["list_price_currency_code"] == "UZS"
    assert body["client_preview"]["fulfillment_policy"] == "milestones"
    assert "internal_notes" not in body["client_preview"]


def test_media_visibility_toggles(world):
    card = _goods(world)
    image = ProductImage.objects.create(product=card, image_url="https://cdn.example/a.png")
    client = _api(world["editor"])

    hidden = client.post(f"{PRODUCTS_URL}{card.pk}/image-visibility/{image.pk}/", {"is_public": False}, format="json")

    assert hidden.json() == {"id": image.pk, "is_public": False}
    image.refresh_from_db()
    assert image.is_public is False
    missing = client.post(f"{PRODUCTS_URL}{card.pk}/document-visibility/999999/", {"is_public": True}, format="json")
    assert missing.status_code == 404


def test_engineering_admin_action_respects_the_threshold(world):
    complete = _goods(world)
    incomplete = _goods(world, name="Без описания", description="")

    count, skipped = publish_products(Product.objects.filter(pk__in=[complete.pk, incomplete.pk]))

    assert count == 1 and skipped == ["Без описания"]
    assert Product.objects.get(pk=incomplete.pk).status.code == "DRAFT"
    assert Product.objects.get(pk=complete.pk).status == ProductStatus.objects.get(code="PUBLISHED")
