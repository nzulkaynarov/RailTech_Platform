"""Client base (Phase 1): seller-created offline clients — Company(is_registered=False)
+ primary Contact, with search-before-create de-dup. See clients.py."""

import pytest
from django.core.exceptions import ValidationError

from accounts.models import Company, CompanyType, Contact, CustomUser
from accounts.services import create_offline_client, find_client_company


@pytest.fixture
def seller(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    return CustomUser.objects.create_user(
        email="rep@seller.test", username="rep@seller.test", password="pw", is_active=True
    )


@pytest.mark.django_db
def test_creates_offline_company_and_primary_contact(seller):
    result, err = create_offline_client(
        seller=seller, company_name="Offline Co", contact_name="Ivan Petrov",
        email="ivan@offline.test", inn="305111222",
    )
    assert err is None
    company, contact = result["company"], result["contact"]
    assert result["company_created"] is True
    assert company.is_registered is False
    assert company.members.count() == 0  # no platform login
    assert "CLIENT" in company.types.values_list("code", flat=True)
    assert contact.is_primary is True
    assert contact.company_id == company.id


@pytest.mark.django_db
def test_dedupes_company_by_inn_and_contact_by_email(seller):
    r1, _ = create_offline_client(
        seller=seller, company_name="Dedupe Co", contact_name="A", email="a@d.test", inn="305333444"
    )
    # Same INN (different name) + same contact email → reuse both, no duplicates.
    r2, _ = create_offline_client(
        seller=seller, company_name="Totally Different Name", contact_name="A2", email="a@d.test", inn="305333444"
    )
    assert r1["company"].id == r2["company"].id
    assert r1["contact"].id == r2["contact"].id
    assert Company.objects.filter(inn="305333444").count() == 1
    assert Contact.objects.filter(company=r1["company"]).count() == 1


@pytest.mark.django_db
def test_second_distinct_contact_is_not_primary(seller):
    r1, _ = create_offline_client(
        seller=seller, company_name="MultiContact Co", contact_name="First", email="first@m.test", inn="305555666"
    )
    r2, _ = create_offline_client(
        seller=seller, company_name="MultiContact Co", contact_name="Second", email="second@m.test", inn="305555666"
    )
    assert r1["company"].id == r2["company"].id
    assert r2["contact"].id != r1["contact"].id
    assert r1["contact"].is_primary is True
    assert r2["contact"].is_primary is False


@pytest.mark.django_db
def test_requires_company_and_contact_name(seller):
    _, err = create_offline_client(seller=seller, company_name="", contact_name="X", email="x@x.test")
    assert err == "CLIENT_FIELDS_REQUIRED"


@pytest.mark.django_db
def test_requires_email_or_phone(seller):
    _, err = create_offline_client(seller=seller, company_name="NoChannel Co", contact_name="X")
    assert err == "CONTACT_NEEDS_EMAIL_OR_PHONE"


@pytest.mark.django_db
def test_contact_model_clean_requires_channel(seller):
    company = Company.objects.create(name="C", is_registered=False)
    with pytest.raises(ValidationError):
        Contact(company=company, name="No Channel").clean()


@pytest.mark.django_db
def test_find_client_company_by_inn_then_name(seller):
    c = Company.objects.create(name="Findable LLC", inn="305777888", is_registered=False)
    assert find_client_company(inn="305777888").id == c.id
    assert find_client_company(name="findable llc").id == c.id  # case-insensitive
    assert find_client_company(name="nope") is None
