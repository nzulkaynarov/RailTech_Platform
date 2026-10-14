"""Отгрузка привязана к договору сделки (`ensure_fulfillment(deal, contract=...)`).

Раньше `ensure_fulfillment` никогда не заполняла `contract`, владелец отгрузки не определялся, и
её видел со-роутед продавец, проигравший заявку (#463). С M1-ERP-02 волна 3 продавец один —
компания-владелец, поэтому видимость проще: отгрузку видят сотрудники своей компании и покупатель
сделки, посторонний — нет. Привязка к договору остаётся данными сделки (накладная, цепочка
документов), и её инварианты — привязка, дозаполнение, неперезапись — проверяются здесь.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Contract, ContractStatus, Deal, DealStage, Fulfillment, FulfillmentStatus, Quote, QuoteStatus
from crm.services.fulfillment import ensure_fulfillment


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "CS", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Pending", "sort_order": 10})


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


@pytest.fixture
def signed_deal(lookups):
    """Заявка покупателя с подписанным договором своей компании; рядом — посторонний (участник
    другой компании-клиента)."""
    buyer_co = Company.objects.create(name="Покупатель", inn="FB904")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))

    winner, winner_co = _seller("Своя компания", "FW904", "staff@fulfil.test")
    loser_co = Company.objects.create(name="Посторонний", inn="FL904")
    loser_co.types.add(CompanyType.objects.get(code="CLIENT"))
    loser = CustomUser.objects.create_user(email="outsider@fulfil.test", username="outsider@fulfil.test", password="x")
    CompanyMember.objects.create(
        user=loser, company=loser_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )

    deal = Deal.objects.create(title="Сделка", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))

    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=winner,
        seller_company=winner_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-FULFIL-904",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {"deal": deal, "contract": contract, "winner": winner, "loser": loser}


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.mark.django_db
class TestFulfillmentOwnerAnchoring:
    def test_ensure_fulfillment_anchors_to_the_contract(self, signed_deal):
        """РЕГРЕСС: отгрузка привязывается к договору сделки."""
        fulfillment = ensure_fulfillment(signed_deal["deal"], contract=signed_deal["contract"])
        assert fulfillment.contract_id == signed_deal["contract"].id

    def test_outsider_does_not_see_the_fulfillment(self, signed_deal):
        """Посторонний (не сотрудник и не покупатель сделки) отгрузку не видит — тот же инвариант,
        что для инвойсов и актов."""
        ensure_fulfillment(signed_deal["deal"], contract=signed_deal["contract"])

        response = _api(signed_deal["loser"]).get("/api/v1/crm/fulfillments/")

        assert response.status_code == 200, response.content
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert rows == [], "посторонний видит отгрузку"

    def test_staff_sees_the_fulfillment(self, signed_deal):
        """Привязка не должна спрятать отгрузку от того, кто её выполняет."""
        ensure_fulfillment(signed_deal["deal"], contract=signed_deal["contract"])

        response = _api(signed_deal["winner"]).get("/api/v1/crm/fulfillments/")

        assert response.status_code == 200, response.content
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert len(rows) == 1, "сотрудник не видит собственную отгрузку"

    def test_call_without_contract_stays_valid(self, signed_deal):
        """Обратная совместимость: сделка без подписанного договора всё ещё получает отгрузку,
        просто без привязки — как было раньше."""
        deal = signed_deal["deal"]
        fulfillment = ensure_fulfillment(deal)
        assert fulfillment.deal_id == deal.id
        assert fulfillment.contract_id is None

    def test_second_call_backfills_a_missing_anchor(self, signed_deal):
        """Идемпотентность + дозаполнение: отгрузка могла быть создана ДО появления договора
        (авто-создание идёт раньше). Повторный вызов с договором обязан привязать её, иначе
        исторические записи навсегда останутся без договора."""
        deal, contract = signed_deal["deal"], signed_deal["contract"]
        first = ensure_fulfillment(deal)
        assert first.contract_id is None

        second = ensure_fulfillment(deal, contract=contract)
        assert second.id == first.id, "создана вторая отгрузка вместо переиспользования"
        assert second.contract_id == contract.id
        assert Fulfillment.objects.filter(deal=deal).count() == 1

    def test_existing_anchor_is_not_overwritten(self, signed_deal):
        """Уже привязанную отгрузку повторный вызов не переписывает другим договором."""
        deal, contract = signed_deal["deal"], signed_deal["contract"]
        ensure_fulfillment(deal, contract=contract)

        other_quote = Quote.objects.create(
            deal=deal,
            version=2,
            status=QuoteStatus.objects.get(code="DRAFT"),
            total_incl_vat=Decimal("1"),
        )
        other = Contract.objects.create(
            deal=deal,
            quote=other_quote,
            number="CT-FULFIL-OTHER",
            status=ContractStatus.objects.get(code="SIGNED"),
            total_amount=Decimal("1"),
        )
        again = ensure_fulfillment(deal, contract=other)
        assert again.contract_id == contract.id
