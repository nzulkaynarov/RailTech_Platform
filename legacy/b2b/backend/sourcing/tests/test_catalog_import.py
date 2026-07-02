from decimal import Decimal
from io import BytesIO

import pandas as pd
import pytest

from sourcing.catalog_import import run_catalog_import


def _xlsx(records):
    """Build an in-memory .xlsx from a list of row dicts."""
    buffer = BytesIO()
    pd.DataFrame(records).to_excel(buffer, index=False)
    return buffer.getvalue()


@pytest.fixture
def lookups(db):
    from catalog.models import ProductStatus, StockStatus
    from master_data.models import Currency, UnitOfMeasure

    Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сўм"})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "В наличии"})
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "шт"})


@pytest.mark.django_db
def test_creates_product_brand_and_offer(lookups, company_factory):
    supplier = company_factory(name="Seller", inn="111111111")
    content = _xlsx(
        [
            {
                "Наименование": "Тормозная колодка",
                "Бренд": "Knorr-Bremse",
                "Артикул производителя": "KB-100",
                "Цена": "150.50",
                "Валюта": "UZS",
                "Наличие": "IN_STOCK",
                "Мин. заказ": "5",
            }
        ]
    )

    result = run_catalog_import(content, supplier_company_id=supplier.id)

    assert result["status"] == "success"
    assert result["created"] == 1
    assert result["offers_upserted"] == 1
    assert result["skipped"] == 0

    from catalog.models import Product, SupplierOffer

    product = Product.objects.get(manufacturer_part_number="KB-100")
    assert product.brand.name == "Knorr-Bremse"
    offer = SupplierOffer.objects.get(product=product, supplier=supplier)
    assert offer.base_price == Decimal("150.50")
    assert offer.currency.code == "UZS"
    assert offer.stock_status.code == "IN_STOCK"
    assert offer.min_order_qty == 5


@pytest.mark.django_db
def test_two_suppliers_same_item_share_one_product(lookups, company_factory):
    supplier_one = company_factory(name="S1", inn="111111111")
    supplier_two = company_factory(name="S2", inn="222222222")
    row = {"Наименование": "Деталь X", "Бренд": "ACME", "Артикул производителя": "A-1", "Цена": "10", "Валюта": "UZS"}

    run_catalog_import(_xlsx([row]), supplier_company_id=supplier_one.id)
    result_two = run_catalog_import(_xlsx([row]), supplier_company_id=supplier_two.id)

    from catalog.models import Product, SupplierOffer

    assert Product.objects.filter(manufacturer_part_number="A-1").count() == 1
    product = Product.objects.get(manufacturer_part_number="A-1")
    assert SupplierOffer.objects.filter(product=product).count() == 2
    assert result_two["created"] == 0
    assert result_two["updated"] == 1


@pytest.mark.django_db
def test_reupload_upserts_offer_not_duplicate(lookups, company_factory):
    supplier = company_factory(name="S", inn="111111111")
    base = {"Наименование": "Y", "Бренд": "B", "Артикул производителя": "Y-1", "Валюта": "UZS"}

    run_catalog_import(_xlsx([{**base, "Цена": "10"}]), supplier_company_id=supplier.id)
    run_catalog_import(_xlsx([{**base, "Цена": "20"}]), supplier_company_id=supplier.id)

    from catalog.models import Product, SupplierOffer

    product = Product.objects.get(manufacturer_part_number="Y-1")
    offers = SupplierOffer.objects.filter(product=product, supplier=supplier)
    assert offers.count() == 1
    assert offers.first().base_price == Decimal("20")


@pytest.mark.django_db
def test_unknown_currency_is_row_error(lookups, company_factory):
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(
        _xlsx([{"Наименование": "Z", "Цена": "10", "Валюта": "XXX"}]), supplier_company_id=supplier.id
    )

    assert result["skipped"] == 1
    assert result["created"] == 0
    assert "UNKNOWN_CURRENCY" in result["errors"][0]["message"]

    from catalog.models import Product

    assert Product.objects.count() == 0


@pytest.mark.django_db
def test_bad_price_is_row_error(lookups, company_factory):
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(_xlsx([{"Наименование": "Z", "Цена": "abc"}]), supplier_company_id=supplier.id)

    assert result["skipped"] == 1
    assert "PRICE_NOT_A_NUMBER" in result["errors"][0]["message"]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_price", ["0", "-5", "-0.01"])
def test_non_positive_price_is_row_error(lookups, company_factory, bad_price):
    """M3: a zero/negative price is a data error — reject the row, write no offer."""
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(
        _xlsx(
            [{"Наименование": "Z", "Бренд": "B", "Артикул производителя": "Z-1", "Цена": bad_price, "Валюта": "UZS"}]
        ),
        supplier_company_id=supplier.id,
    )

    assert result["created"] == 0
    assert result["offers_upserted"] == 0
    assert result["skipped"] == 1
    assert "PRICE_NOT_POSITIVE" in result["errors"][0]["message"]

    from catalog.models import Product, SupplierOffer

    assert SupplierOffer.objects.count() == 0
    assert not Product.objects.filter(manufacturer_part_number="Z-1").exists()


@pytest.mark.django_db
def test_name_without_price_creates_no_offer(lookups, company_factory):
    """M3: a name-only row creates the PIM card but NO empty offer."""
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(
        _xlsx([{"Наименование": "OnlyName", "Бренд": "B", "Артикул производителя": "N-1"}]),
        supplier_company_id=supplier.id,
    )

    assert result["created"] == 1
    assert result["offers_upserted"] == 0
    assert result["skipped"] == 0

    from catalog.models import SupplierOffer

    assert SupplierOffer.objects.count() == 0


@pytest.mark.django_db
def test_products_only_when_no_supplier(lookups):
    result = run_catalog_import(
        _xlsx([{"Наименование": "NoOffer", "Цена": "10", "Валюта": "UZS"}]), supplier_company_id=None
    )

    assert result["created"] == 1
    assert result["offers_upserted"] == 0

    from catalog.models import SupplierOffer

    assert SupplierOffer.objects.count() == 0


@pytest.mark.django_db
def test_dry_run_persists_nothing(lookups, company_factory):
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(
        _xlsx([{"Наименование": "Dry", "Бренд": "DB", "Артикул производителя": "D-1", "Цена": "10", "Валюта": "UZS"}]),
        supplier_company_id=supplier.id,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["created"] == 1
    assert result["offers_upserted"] == 1

    from catalog.models import Manufacturer, Product, SupplierOffer

    assert Product.objects.count() == 0
    assert SupplierOffer.objects.count() == 0
    assert Manufacturer.objects.count() == 0


@pytest.mark.django_db
def test_blank_rows_skipped_silently(lookups, company_factory):
    supplier = company_factory(inn="111111111")
    result = run_catalog_import(
        _xlsx([{"Наименование": "", "Цена": "10"}, {"Наименование": "Real", "Цена": "5", "Валюта": "UZS"}]),
        supplier_company_id=supplier.id,
    )

    assert result["created"] == 1
    assert result["skipped"] == 0


@pytest.mark.django_db
def test_no_name_column_raises(lookups, company_factory):
    supplier = company_factory(inn="111111111")
    with pytest.raises(ValueError):
        run_catalog_import(_xlsx([{"Цена": "10"}]), supplier_company_id=supplier.id)


@pytest.mark.django_db
def test_import_stamps_owner_company(lookups, company_factory):
    """C3: a bulk-imported product is owned by the importing seller so they can
    see/manage it (without this it's orphaned + invisible)."""
    supplier = company_factory(name="Importer", inn="111111111")
    run_catalog_import(
        _xlsx(
            [
                {
                    "Наименование": "Реле",
                    "Бренд": "Siemens",
                    "Артикул производителя": "S-1",
                    "Цена": "10",
                    "Валюта": "UZS",
                }
            ]
        ),
        supplier_company_id=supplier.id,
    )
    from catalog.models import Product

    product = Product.objects.get(manufacturer_part_number="S-1")
    assert product.owner_company_id == supplier.id


@pytest.mark.django_db
def test_import_backfills_orphan_but_never_hijacks_other_tenant(lookups, company_factory):
    """C3 safety: de-dup matches globally on brand+MPN. An import must backfill an
    ORPHAN's owner, but must NOT steal a product another tenant already owns."""
    from catalog.models import Manufacturer, Product

    owner_a = company_factory(name="OwnerA", inn="111111111")
    importer_b = company_factory(name="ImporterB", inn="222222222")
    brand = Manufacturer.objects.create(name="ACME")
    owned = Product.objects.create(name="X", brand=brand, manufacturer_part_number="A-1", owner_company=owner_a)
    orphan = Product.objects.create(name="Y", brand=brand, manufacturer_part_number="A-2", owner_company=None)

    def row(mpn):
        return {
            "Наименование": "upd",
            "Бренд": "ACME",
            "Артикул производителя": mpn,
            "Цена": "9",
            "Валюта": "UZS",
        }

    run_catalog_import(_xlsx([row("A-1"), row("A-2")]), supplier_company_id=importer_b.id)

    owned.refresh_from_db()
    orphan.refresh_from_db()
    assert owned.owner_company_id == owner_a.id  # NOT hijacked by importer B
    assert orphan.owner_company_id == importer_b.id  # orphan backfilled


@pytest.mark.django_db
def test_catalog_template_download(lookups, user_factory):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user_factory(email="seller@example.com", username="seller"))

    response = client.get("/api/v1/sourcing/catalog-template/")

    assert response.status_code == 200
    assert "spreadsheetml" in response["Content-Type"]
    assert response["Content-Disposition"].endswith('.xlsx"')
    assert len(response.content) > 0
