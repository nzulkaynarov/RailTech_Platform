"""X-16: обязательные коды для публикации — МХИК у позиции, которую продаём, ТН ВЭД у ввозимой (настройки компании)."""

import pytest
from parties.models import CompanySettings

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.testing import grant_head, make_own_company
from catalog.completeness import completeness
from catalog.models import Category, DomainType, Product, ProductStatus
from catalog.publishing import publish_product
from core.models import Country
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db

MXIK = "73020010001000001"


@pytest.fixture
def world(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    company = make_own_company(Company.objects.create(name="ООО Издатель", inn="9300000001"))
    user = CustomUser.objects.create_user(email="own@codes.test", username="own@codes.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    grant_head(user, company)
    uom, _ = UnitOfMeasure.objects.get_or_create(code="H87", defaults={"name": "шт.", "sort_order": 10})
    domain, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "Общие товары", "sku_prefix": "GG", "sort_order": 20}
    )
    category, _ = Category.objects.get_or_create(name="Крепёж", defaults={"domain_type": domain})
    return {"company": company, "user": user, "uom": uom, "domain": domain, "category": category}


def _card(world, **kwargs):
    defaults = {
        "name": "Накладка рельсовая",
        "owner_company": world["company"],
        "status": ProductStatus.objects.get(code="DRAFT"),
        "domain_type": world["domain"],
        "uom": world["uom"],
        "category": world["category"],
        "hs_code": "7302100000",
        "mxik_code": MXIK,
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def _policy(world, **fields):
    CompanySettings.objects.update_or_create(company=world["company"], defaults=fields)


def test_mxik_is_required_to_publish_by_default_and_the_reason_names_it(world):
    card = _card(world, mxik_code="")

    published, error = publish_product(card, world["user"])

    assert published is None and error == "PRODUCT_INCOMPLETE:mxik_code"
    assert completeness(card)["missing"] == [{"code": "mxik_code", "label": "Код МХИК (ИКПУ)"}]


def test_mxik_blocks_publishing_whatever_the_completeness_threshold(world):
    _policy(world, catalog_publish_threshold=1)
    card = _card(world, mxik_code="")

    assert completeness(card)["is_publishable"] is False
    assert publish_product(card, world["user"])[1] == "PRODUCT_INCOMPLETE:mxik_code"


def test_mxik_not_required_when_the_company_turns_the_setting_off(world):
    _policy(world, catalog_require_mxik=False)
    card = _card(world, mxik_code="")

    assert publish_product(card, world["user"])[1] is None


def test_services_need_mxik_too(world):
    services, _ = DomainType.objects.get_or_create(
        code="SERVICES", defaults={"name": "Услуги", "sku_prefix": "SV", "sort_order": 30}
    )
    card = _card(world, domain_type=services, hs_code="", mxik_code="")

    assert publish_product(card, world["user"])[1] == "PRODUCT_INCOMPLETE:mxik_code"


def test_hs_code_is_required_for_an_imported_item_whatever_the_threshold(world):
    _policy(world, catalog_publish_threshold=1)
    card = _card(world, hs_code="")  # origin unknown — counts as imported

    assert publish_product(card, world["user"])[1] == "PRODUCT_INCOMPLETE:hs_code"


def test_domestic_item_does_not_need_hs_code(world):
    uzbekistan, _ = Country.objects.get_or_create(code="UZ", defaults={"name": "Узбекистан", "sort_order": 10})
    card = _card(world, hs_code="", country_of_origin=uzbekistan)

    assert publish_product(card, world["user"])[1] is None


def test_hs_code_not_required_when_the_company_turns_the_setting_off(world):
    _policy(world, catalog_require_hs_imported=False)
    card = _card(world, hs_code="")

    assert publish_product(card, world["user"])[1] is None


def test_already_published_item_stays_published_the_check_applies_on_the_next_publish(world):
    card = _card(world, mxik_code="", status=ProductStatus.objects.get(code="PUBLISHED"))

    card.refresh_from_db()
    assert card.status.code == "PUBLISHED", "настройка не снимает с витрины"
    assert [m["code"] for m in completeness(card)["missing"]] == ["mxik_code"], "а при следующей публикации — спросят"
    publish_product(card, world["user"])  # unpublish/publish cycle goes through the same check
    from catalog.publishing import unpublish_product

    unpublish_product(card, world["user"])
    assert publish_product(Product.objects.get(pk=card.pk), world["user"])[1] == "PRODUCT_INCOMPLETE:mxik_code"


def test_admin_publish_action_does_not_bypass_the_required_codes(world):
    from catalog import services

    without = _card(world, name="Без МХИК", mxik_code="")
    complete = _card(world, name="С МХИК")

    updated, skipped = services.publish_products(Product.objects.filter(pk__in=[without.pk, complete.pk]))

    without.refresh_from_db()
    complete.refresh_from_db()
    assert updated == 1 and skipped == ["Без МХИК"]
    assert without.status.code == "DRAFT" and complete.status.code == "PUBLISHED"
