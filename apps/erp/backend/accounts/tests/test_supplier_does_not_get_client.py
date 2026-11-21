"""K0: поставщик не получает CLIENT даром (сигнал «продавец тоже покупает» удалён); СЦ-8: компания, у которой сняли последнюю роль, остаётся без ролей."""

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


def test_removing_the_last_type_leaves_the_company_without_roles():
    """Fact: a role is an explicit mark; nothing re-adds CLIENT when the last one is removed (СЦ-8)."""
    _type("CLIENT")
    company = Company.objects.create(name="Untyped", inn="8400001")
    company.types.add(_type("SUPPLIER"))

    company.types.clear()

    assert _codes(company) == set()
    assert not Company.objects.filter(types__code="CLIENT", pk=company.pk).exists()


def test_removing_one_of_two_types_keeps_the_other_and_adds_nothing():
    company = Company.objects.create(name="Two", inn="8400002")
    _type("CLIENT")
    company.types.add(_type("SUPPLIER"), _type("MANUFACTURER"))

    company.types.remove(_type("MANUFACTURER"))

    assert _codes(company) == {"SUPPLIER"}


def test_client_added_explicitly_stays_next_to_supplier():
    company = Company.objects.create(name="Both", inn="8500001")

    company.types.add(_type("SUPPLIER"), _type("CLIENT"))

    assert _codes(company) == {"SUPPLIER", "CLIENT"}


def test_company_whose_last_role_was_removed_is_not_in_the_client_book():
    """СЦ-8: no role, no deals, no CRM mapping — the company is out of the client book (its role does not reappear)."""
    from accounts.services.clients import client_book_q

    _type("CLIENT")
    company = Company.objects.create(name="Ex Supplier", inn="8600001")
    company.types.add(_type("SUPPLIER"))
    assert not Company.objects.filter(client_book_q(), pk=company.pk).exists()

    company.types.remove(_type("SUPPLIER"))

    assert _codes(company) == set()
    assert not Company.objects.filter(client_book_q(), pk=company.pk).exists()


def test_desk_role_switch_off_leaves_the_company_without_roles():
    """The desk path (`service_counterparty.set_role`) — the one that used to trigger the CLIENT auto-restore."""
    from portal.desk.service_counterparty import set_role

    _type("CLIENT")
    company = Company.objects.create(name="Desk Supplier", inn="8700001")
    company.types.add(_type("SUPPLIER"))
    actor = CustomUser.objects.create_superuser(username="r@example.com", email="r@example.com", password="x")

    set_role(company, "supplier", False, actor=actor)

    assert _codes(company) == set()
