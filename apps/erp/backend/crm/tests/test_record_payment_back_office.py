"""Оплату фиксирует бэк-офис (M1-ERP-02 волна 3, поручение координатора).

Продавец любой сделки — своя компания (BUSINESS §3.3), поэтому входящий платёж по счёту клиенту
проводит её сотрудник с правом финансов `payment.record` — явным правом роли (fail-closed, как у
`quote.send` / `contract.sign`: флаг участника `can_buy` по умолчанию True и права не даёт).
Покупательская ветка (участник компании-клиента с `can_buy`) остаётся для портала до M2-ERP-01.

Матрица на эндпоинте `POST /crm/invoices/{id}/record-payment/`:
сотрудник с правом — 201 и платёж записан; сотрудник без права — 403 `ROLE_NOT_PERMITTED`;
посторонний — 403 `MEMBER_REQUIRED_FOR_ACTION`; ни в одном отказе деньги не двигаются.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import Contract, ContractStatus, Deal, DealStage, InvoiceStatus, Quote, QuoteStatus
from crm.services.billing import generate_invoice_from_contract


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "Signed", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})

    def company(name, inn, type_code):
        obj = Company.objects.create(name=name, inn=inn)
        obj.types.add(CompanyType.objects.get(code=type_code))
        return obj

    def member(company_obj, email, permissions):
        user = CustomUser.objects.create_user(email=email, username=email, password="x")
        role = CompanyRole.objects.create(company=company_obj, name=email, permissions=permissions)
        CompanyMember.objects.create(
            user=user,
            company=company_obj,
            role=WorkspaceRole.objects.get(code="MEMBER"),
            company_role=role,
            is_active=True,
            is_primary=True,
        )
        return user

    own = company("Own Co", "S903", "SUPPLIER")
    client = company("Client Co", "B903", "CLIENT")
    stranger_co = company("Stranger Co", "O903", "CLIENT")
    deal = Deal.objects.create(title="Сделка", company=client, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company=own,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-PAY-903",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice, error = generate_invoice_from_contract(contract.id, actor=None)
    assert error is None, error
    invoice.status = InvoiceStatus.objects.get(code="ISSUED")
    invoice.save(update_fields=["status"])
    return {
        "invoice": invoice,
        "finance": member(own, "finance@own.test", ["payment.record"]),
        "sales": member(own, "sales@own.test", ["quote.build", "quote.send"]),
        "stranger": member(stranger_co, "stranger@other.test", ["payment.record"]),
    }


def _pay(user, invoice):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client.post(
        f"/api/v1/crm/invoices/{invoice.id}/record-payment/",
        {"amount": "112.00", "paid_at": "2026-10-14"},
        format="json",
    )


def test_staff_with_payment_permission_records_payment(world):
    response = _pay(world["finance"], world["invoice"])
    assert response.status_code == 201, response.content
    world["invoice"].refresh_from_db()
    assert world["invoice"].amount_paid == Decimal("112.00")
    assert world["invoice"].status_code == "PAID"


@pytest.mark.parametrize(
    ("who", "code"),
    [("sales", "ROLE_NOT_PERMITTED"), ("stranger", "MEMBER_REQUIRED_FOR_ACTION")],
)
def test_payment_without_the_right_is_refused(world, who, code):
    response = _pay(world[who], world["invoice"])
    assert response.status_code == 403, response.content
    assert response.json()["detail"] == code
    world["invoice"].refresh_from_db()
    assert world["invoice"].amount_paid == Decimal("0")
