"""Client base (Phase 1+2): staff-created offline clients — Company(is_registered=False)
+ primary Contact, in the own company's book (the team's book; not global). See clients.py."""

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
def test_teammate_reuses_the_teams_client_and_outsider_is_refused(seller):
    """The book belongs to the own company: a colleague creating the same INN reuses the SAME
    record (search-before-create within the team's book); a non-staff user cannot create clients."""
    r1, _ = create_offline_client(
        seller=seller, company_name="Shared RealCo", contact_name="A", email="a@s.test", inn="305999000"
    )
    own = seller.memberships.get().company
    teammate = CustomUser.objects.create_user(email="mate@sellerA.test", username="mate@sellerA.test", password="pw")
    CompanyMember.objects.create(
        user=teammate, company=own, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    r2, _ = create_offline_client(
        seller=teammate, company_name="Shared RealCo", contact_name="B", email="b@s.test", inn="305999000"
    )
    assert r1["company"].id == r2["company"].id  # one team book, no duplicate
    assert seller_clients(seller).count() == 1
    assert seller_clients(teammate).count() == 1

    outsider_co = Company.objects.create(name="Outsider", inn="700000002")
    outsider_co.types.add(CompanyType.objects.get(code="CLIENT"))
    outsider = CustomUser.objects.create_user(email="rep@other.test", username="rep@other.test", password="pw")
    CompanyMember.objects.create(
        user=outsider, company=outsider_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    result, err = create_offline_client(
        seller=outsider, company_name="Shared RealCo", contact_name="C", email="c@s.test", inn="305999000"
    )
    assert result is None and err == "ONLY_SELLER_CAN_CREATE_CLIENTS"
    assert seller_clients(outsider).count() == 0  # the team's client is invisible to an outsider


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
    # Findable by TIN and, within the book, by name.
    created, _ = create_offline_client(
        seller=seller, company_name="Findable LLC", contact_name="C", email="c@f.test", inn="305777888"
    )
    assert find_client_company(seller, inn="305777888").id == created["company"].id
    assert find_client_company(seller, name="findable llc").id == created["company"].id  # case-insensitive
    assert find_client_company(seller, name="nope") is None


@pytest.mark.django_db
def test_supplier_recorded_as_client_is_reused_and_marked_client(seller):
    """СЦ-12: поставщик, которого записывают клиентом, — та же компания (ADR-0028), теперь и с типом CLIENT."""
    supplier = Company.objects.create(name="Supplier North", inn="305000111")
    supplier.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    before = Company.objects.count()

    result, err = create_offline_client(
        seller=seller, company_name="Другое имя", contact_name="A", email="a@sn.test", inn="305000111"
    )

    assert err is None
    assert result["company_created"] is False
    assert result["company"].pk == supplier.pk
    assert {"SUPPLIER", "CLIENT"} <= set(supplier.types.values_list("code", flat=True))
    assert supplier in seller_clients(seller)
    assert Company.objects.count() == before


@pytest.mark.django_db
def test_crm_client_with_tin_in_inn_field_is_reused(seller):
    from integration.models import CrmClientMapping

    company = Company.objects.create(name="CRM Client", inn="305000222")
    CrmClientMapping.objects.create(crm_client_id=5222, company=company)

    result, err = create_offline_client(
        seller=seller, company_name="CRM Client", contact_name="B", email="b@crm.test", inn="305000222"
    )

    assert err is None
    assert result["company"].pk == company.pk


@pytest.mark.django_db
def test_never_reuses_own_company_by_tin(seller):
    own_id = CompanyMember.objects.get(user=seller).company_id

    result, err = create_offline_client(
        seller=seller, company_name="Same TIN Buyer", contact_name="C", email="c@own.test", inn="700000001"
    )

    assert err is None
    assert result["company_created"] is True
    assert result["company"].pk != own_id


@pytest.mark.django_db
def test_archived_company_with_the_same_tin_is_not_reused(seller):
    archived = Company.objects.create(name="Old Buyer", inn="305000333", is_active=False)

    result, err = create_offline_client(
        seller=seller, company_name="Old Buyer", contact_name="D", email="d@old.test", inn="305000333"
    )

    assert err is None
    assert result["company_created"] is True
    assert result["company"].pk != archived.pk
