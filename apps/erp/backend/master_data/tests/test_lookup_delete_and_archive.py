"""
Справочники: опасное действие обязано называть причину, а отключённая строка — возвращаться.

Две находки прогона 20-08, подтверждённые замером 24-08:

1. DELETE строки, на которую ссылаются данные арендаторов, отдавал 500 с HTML-страницей
   вместо формы `{"detail": "<CODE>"}`. Данные при этом целы — PROTECT срабатывал, — но
   оператор видел безымянное «Не удалось удалить» и повторял попытку, а в Sentry падала
   ложная авария. Проверяется по ВСЕМ четырём справочникам: точечная починка одной вкладки
   оставила бы три такие же пятисотки.

2. Отключённая (`is_active=False`) строка исчезала из списка навсегда: перебор параметров
   не возвращал её ни одним способом, а значит вернуть её через интерфейс было нельзя —
   гасил её тот же оператор, который не мог включить обратно.

Отдельно закреплён каскад, найденный тем же замером: `ChargeTemplate.delivery_basis` стоял
с CASCADE, и удаление базиса поставки МОЛЧА уносило шаблоны статей расхода арендатора.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import CustomUser, SystemRole
from master_data.models import Country, Currency, DeliveryBasis, UnitOfMeasure


@pytest.fixture(autouse=True)
def clear_lookup_cache():
    """Список справочника кэшируется; между замерами кэш обязан быть пуст, иначе тест
    померил бы прошлый ответ, а не поведение."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        is_superuser=True,
        email="lookup.operator@test.uz",
        username="lookup_operator",
        password="Probe1234!",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── 1. Отказ вместо пятисотки — по каждому справочнику ──────────────────────


def _referenced_unit(db):
    from catalog.models import Category, Product

    unit = UnitOfMeasure.objects.create(code="SBX_UOM", name="Песочная единица", sort_order=900)
    category = Category.objects.create(name="Песочная категория")
    Product.objects.create(name="Товар песочницы", category=category, uom=unit)
    return unit


def _referenced_currency(db):
    from master_data.models import ExchangeRate

    currency = Currency.objects.create(code="SBX", name="Песочный сум", sort_order=900)
    ExchangeRate.objects.create(currency=currency, rate_to_uzs="1.0000", rate_date="2026-08-24")
    return currency


def _referenced_country(db):
    from catalog.models import Manufacturer

    # Справочник стран засеян по ISO 3166-1 миграцией — код песочницы обязан быть
    # заведомо не-ISO, иначе тест падает на дубле, а не меряет отказ.
    country = Country.objects.create(code="ZZ", name="Песочная страна", sort_order=900)
    Manufacturer.objects.create(name="Песочный завод", country=country)
    return country


def _referenced_basis(db):
    from accounts.models import Company
    from catalog.models import Manufacturer, Product, SupplierOffer

    basis = DeliveryBasis.objects.create(code="SBX_DB", name="Песочный базис", sort_order=900)
    unit = UnitOfMeasure.objects.create(code="SBX_UOM2", name="Единица 2", sort_order=901)
    from catalog.models import Category

    category = Category.objects.create(name="Категория 2")
    product = Product.objects.create(name="Товар 2", category=category, uom=unit)
    company = Company.objects.create(name="Песочный поставщик", inn="907999001")
    Manufacturer.objects.create(name="Завод 2")
    SupplierOffer.objects.create(product=product, supplier=company, base_price="10.00", delivery_basis=basis)
    return basis


@pytest.mark.parametrize(
    "kind,factory",
    [
        ("units", _referenced_unit),
        ("currencies", _referenced_currency),
        ("countries", _referenced_country),
        ("delivery-basis", _referenced_basis),
    ],
)
def test_delete_of_a_referenced_row_is_refused_by_name(kind, factory, operator, db):
    row = factory(db)

    resp = _api(operator).delete(f"/api/v1/master-data/{kind}/{row.pk}/")

    assert resp.status_code == 400, "PROTECT обязан приходить отказом, а не пятисоткой"
    detail = resp.json()["detail"]
    assert detail.split(":")[0] == "LOOKUP_IN_USE"
    assert ":" in detail, "отказ обязан называть, ЧТО держит строку"
    assert type(row).objects.filter(pk=row.pk).exists(), "отказ ничего не удаляет"


def test_delete_of_an_unreferenced_row_still_works(operator, db):
    """Обратная сторона: запрет не превратился в «удалить нельзя ничего»."""
    row = UnitOfMeasure.objects.create(code="SBX_FREE", name="Ничем не занята", sort_order=910)

    resp = _api(operator).delete(f"/api/v1/master-data/units/{row.pk}/")

    assert resp.status_code == 204
    assert not UnitOfMeasure.objects.filter(pk=row.pk).exists()


# ── 2. Отключённая строка возвращается ──────────────────────────────────────


def test_deactivated_row_is_hidden_from_everyone_by_default(operator, db):
    row = UnitOfMeasure.objects.create(code="SBX_OFF", name="Отключаемая", sort_order=920, is_active=False)

    body = _api(operator).get("/api/v1/master-data/units/").json()

    assert not any(item["code"] == "SBX_OFF" for item in body), "выпадающие списки не показывают отключённое"
    assert row.pk


def test_operator_can_see_and_restore_a_deactivated_row(operator, db):
    row = UnitOfMeasure.objects.create(code="SBX_OFF2", name="Отключаемая 2", sort_order=921, is_active=False)
    client = _api(operator)

    body = client.get("/api/v1/master-data/units/?include_inactive=1").json()
    assert any(item["code"] == "SBX_OFF2" for item in body), "оператору отключённые видны по явному запросу"

    resp = client.patch(f"/api/v1/master-data/units/{row.pk}/", {"is_active": True}, format="json")
    assert resp.status_code == 200
    row.refresh_from_db()
    assert row.is_active is True


def test_anonymous_cannot_see_deactivated_rows_even_when_asking(db):
    """Ключ кэша обязан различать выборки: привилегированный ответ не должен осесть в общем."""
    UnitOfMeasure.objects.create(code="SBX_OFF3", name="Отключаемая 3", sort_order=922, is_active=False)
    anon = APIClient()

    body = anon.get("/api/v1/master-data/units/?include_inactive=1").json()

    assert not any(item["code"] == "SBX_OFF3" for item in body)


def test_privileged_answer_does_not_leak_into_the_shared_cache(operator, db):
    """Сначала спрашивает оператор с флагом, потом аноним без флага — второй обязан получить
    активные, а не осевший в кэше привилегированный ответ."""
    UnitOfMeasure.objects.create(code="SBX_OFF4", name="Отключаемая 4", sort_order=923, is_active=False)

    privileged = _api(operator).get("/api/v1/master-data/units/?include_inactive=1").json()
    assert any(item["code"] == "SBX_OFF4" for item in privileged)

    shared = APIClient().get("/api/v1/master-data/units/").json()
    assert not any(item["code"] == "SBX_OFF4" for item in shared)


# ── 3. Каскад, уносивший данные арендатора ──────────────────────────────────


def test_deleting_a_delivery_basis_no_longer_wipes_tenant_charge_templates(operator, db):
    """До 24-08 `ChargeTemplate.delivery_basis` стоял с CASCADE: DELETE базиса возвращал 204
    и МОЛЧА уносил шаблоны статей расхода арендатора."""
    from accounts.models import Company
    from crm.models import ChargeTemplate, ChargeType

    basis = DeliveryBasis.objects.create(code="SBX_DB2", name="Базис с шаблоном", sort_order=930)
    company = Company.objects.create(name="Арендатор шаблона", inn="907999002")
    charge_type = ChargeType.objects.create(code="SBX_CT", name="Песочная статья", sort_order=900)
    template = ChargeTemplate.objects.create(company=company, delivery_basis=basis, charge_type=charge_type)

    resp = _api(operator).delete(f"/api/v1/master-data/delivery-basis/{basis.pk}/")

    assert resp.status_code == 400
    assert resp.json()["detail"].split(":")[0] == "LOOKUP_IN_USE"
    assert ChargeTemplate.objects.filter(pk=template.pk).exists(), "шаблон арендатора обязан уцелеть"
    assert DeliveryBasis.objects.filter(pk=basis.pk).exists()
