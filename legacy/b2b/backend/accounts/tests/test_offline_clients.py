"""Client base (Phase 1+2): seller-created offline clients — Company(is_registered=False)
+ primary Contact, scoped to the seller's OWN book (not global). See clients.py."""

import pytest
from django.core.exceptions import ValidationError

from accounts.models import Company, CompanyMember, CompanyType, Contact, CustomUser, WorkspaceRole
from accounts.services import create_offline_client, find_client_company
from accounts.services.clients import seller_clients


def _make_seller(email, inn):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})[0]
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    owner = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    co = Company.objects.create(name=f"Seller {email}", inn=inn)
    co.types.add(supplier)
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=co, role=owner, is_active=True, can_sell=True)
    return user


@pytest.fixture
def seller(db):
    return _make_seller("rep@sellerA.test", "700000001")


@pytest.mark.django_db
def test_creates_offline_company_and_primary_contact(seller):
    result, err = create_offline_client(
        seller=seller,
        company_name="Offline Co",
        contact_name="Ivan Petrov",
        email="ivan@offline.test",
        inn="305111222",
    )
    assert err is None
    company, contact = result["company"], result["contact"]
    assert result["company_created"] is True
    assert company.is_registered is False
    assert company.members.count() == 0  # no platform login
    assert "CLIENT" in company.types.values_list("code", flat=True)
    assert contact.is_primary is True
    assert contact.created_by_id == seller.id


@pytest.mark.django_db
def test_dedupes_within_own_book_by_inn_and_email(seller):
    r1, _ = create_offline_client(
        seller=seller, company_name="Dedupe Co", contact_name="A", email="a@d.test", inn="305333444"
    )
    # Same INN (different name) + same contact email, SAME seller → reuse both.
    r2, _ = create_offline_client(
        seller=seller, company_name="Different Name", contact_name="A2", email="a@d.test", inn="305333444"
    )
    assert r1["company"].id == r2["company"].id
    assert r1["contact"].id == r2["contact"].id


@pytest.mark.django_db
def test_other_seller_does_not_see_or_reuse_first_sellers_client(seller):
    """Confidentiality + per-book scoping: a different seller creating the same INN gets
    a SEPARATE record (cross-tenant dups are allowed; admin reconciles at KYC)."""
    r1, _ = create_offline_client(
        seller=seller, company_name="Shared RealCo", contact_name="A", email="a@s.test", inn="305999000"
    )
    seller_b = _make_seller("rep@sellerB.test", "700000002")
    r2, _ = create_offline_client(
        seller=seller_b, company_name="Shared RealCo", contact_name="B", email="b@s.test", inn="305999000"
    )
    assert r1["company"].id != r2["company"].id  # separate private records
    assert seller_clients(seller).count() == 1
    assert seller_clients(seller_b).count() == 1
    assert r2["company"] not in seller_clients(seller)  # B's client invisible to A


@pytest.mark.django_db
def test_second_distinct_contact_is_not_primary(seller):
    r1, _ = create_offline_client(
        seller=seller, company_name="MultiContact Co", contact_name="First", email="first@m.test", inn="305555666"
    )
    r2, _ = create_offline_client(
        seller=seller, company_name="MultiContact Co", contact_name="Second", email="second@m.test", inn="305555666"
    )
    assert r1["company"].id == r2["company"].id
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
def test_find_client_company_scoped_to_book(seller):
    # A company only becomes findable once it's in the seller's book (has their contact).
    created, _ = create_offline_client(
        seller=seller, company_name="Findable LLC", contact_name="C", email="c@f.test", inn="305777888"
    )
    assert find_client_company(seller, inn="305777888").id == created["company"].id
    assert find_client_company(seller, name="findable llc").id == created["company"].id  # case-insensitive
    assert find_client_company(seller, name="nope") is None
