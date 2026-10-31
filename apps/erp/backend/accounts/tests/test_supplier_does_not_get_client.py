"""K0: поставщик не получает CLIENT даром (сигнал «продавец тоже покупает» удалён); компания без типов — по-прежнему клиент."""

import pytest
from django.contrib import admin as django_admin
from django.test import RequestFactory
from parties.models import Company, CompanyType

from accounts.admin import CompanyAdmin
from accounts.models import CustomUser

pytestmark = pytest.mark.django_db


def _type(code):
    return CompanyType.objects.get_or_create(code=code, defaults={"name": code})[0]


def _codes(company):
    return set(company.types.values_list("code", flat=True))


@pytest.mark.parametrize("code", ["SUPPLIER", "MANUFACTURER"])
def test_seller_type_added_through_orm_does_not_add_client(code):
    _type("CLIENT")
    company = Company.objects.create(name="Seller " + code, inn="810" + str(len(code)))

    company.types.add(_type(code))

    assert _codes(company) == {code}


def test_seller_type_set_and_create_paths_do_not_add_client():
    _type("CLIENT")
    company = Company.objects.create(name="Seller Set", inn="8200001")

    company.types.set([_type("SUPPLIER")])
    through = Company.types.through
    other = Company.objects.create(name="Seller Through", inn="8200002")
    through.objects.create(company=other, companytype=_type("SUPPLIER"))

    assert _codes(company) == {"SUPPLIER"}
    assert _codes(other) == {"SUPPLIER"}


def test_seller_created_in_admin_form_does_not_get_client():
    _type("CLIENT")
    supplier = _type("SUPPLIER")
    model_admin = CompanyAdmin(Company, django_admin.site)
    request = RequestFactory().post("/admin/parties/company/add/")
    request.user = CustomUser.objects.create_superuser(
        username="root@example.com", email="root@example.com", password="x"
    )
    form_class = model_admin.get_form(request, fields=["name", "inn", "types"])

    form = form_class(data={"name": "Admin Supplier", "inn": "830000011", "types": [supplier.pk]})
    assert form.is_valid(), form.errors
    company = form.save()

    assert _codes(company) == {"SUPPLIER"}


def test_removing_the_last_type_still_restores_client_default():
    client = _type("CLIENT")
    company = Company.objects.create(name="Untyped", inn="8400001")
    company.types.add(_type("SUPPLIER"))

    company.types.clear()

    assert _codes(company) == {client.code}


def test_client_added_explicitly_stays_next_to_supplier():
    company = Company.objects.create(name="Both", inn="8500001")

    company.types.add(_type("SUPPLIER"), _type("CLIENT"))

    assert _codes(company) == {"SUPPLIER", "CLIENT"}
