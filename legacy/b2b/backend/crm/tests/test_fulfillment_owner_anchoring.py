"""Отгрузка должна быть привязана к владельцу — иначе её видит проигравший конкурент.

Видимость биллинга у продавца строится так (`crm/views/billing.py:_seller_side_q`): документ
принадлежит продавцу, если он ПРИВЯЗАН к его компании (через `contract → quote.seller_company`),
либо владелец не определён — тогда действует фолбэк «виден любому зароутиненному продавцу».

Комментарий к фолбэку прямо утверждает: «This never re-exposes a winner's billing to a losing
co-routed seller, because the winner's docs ARE owner-anchored».

Для `Fulfillment` этот инвариант нарушался: `ensure_fulfillment` никогда не заполняла
`contract`, поэтому владелец НЕ определялся никогда, и отгрузка выигранной сделки уходила в
фолбэк — её видел проигравший со-роутед продавец. Это граница конфиденциальности
(«скрытая конкуренция», ADR-0003 §5), а не косметика.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Quote,
    QuoteStatus,
)
from crm.services.fulfillment import ensure_fulfillment


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "CS", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Pending", "sort_order": 10})


def _seller(name, inn, email):
    company = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
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
    SupplierSubscription.objects.create(
        company=company,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.now().date() + timedelta(days=30),
    )
    return user, company


@pytest.fixture
def multiseller_deal(lookups):
    """Заявка покупателя, зароутиненная на ДВУХ продавцов; выиграл первый."""
    buyer_co = Company.objects.create(
        name="Покупатель", inn="FB904", verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))

    winner, winner_co = _seller("Победитель", "FW904", "winner@fulfil.test")
    loser, loser_co = _seller("Проигравший", "FL904", "loser@fulfil.test")

    deal = Deal.objects.create(title="Сделка", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    # Оба продавца зароутинены на заявку — «скрытая конкуренция».
    DealSellerRouting.objects.create(deal=deal, seller_company=winner_co)
    DealSellerRouting.objects.create(deal=deal, seller_company=loser_co)

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
    def test_ensure_fulfillment_anchors_to_the_winning_contract(self, multiseller_deal):
        """РЕГРЕСС. Без привязки владелец не определяется, и работает фолбэк."""
        fulfillment = ensure_fulfillment(multiseller_deal["deal"], contract=multiseller_deal["contract"])
        assert fulfillment.contract_id == multiseller_deal["contract"].id

    def test_losing_seller_does_not_see_the_winners_fulfillment(self, multiseller_deal):
        """ГЛАВНОЕ. Проигравший со-роутед продавец не должен видеть отгрузку победителя —
        тот же инвариант, что для инвойсов и актов («скрытая конкуренция», ADR-0003 §5)."""
        ensure_fulfillment(multiseller_deal["deal"], contract=multiseller_deal["contract"])

        response = _api(multiseller_deal["loser"]).get("/api/v1/crm/fulfillments/")

        assert response.status_code == 200, response.content
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert rows == [], "проигравший продавец видит отгрузку победителя"

    def test_winning_seller_still_sees_its_own_fulfillment(self, multiseller_deal):
        """Привязка не должна спрятать отгрузку от того, кто её выполняет."""
        ensure_fulfillment(multiseller_deal["deal"], contract=multiseller_deal["contract"])

        response = _api(multiseller_deal["winner"]).get("/api/v1/crm/fulfillments/")

        assert response.status_code == 200, response.content
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert len(rows) == 1, "победитель не видит собственную отгрузку"

    def test_call_without_contract_stays_valid(self, multiseller_deal):
        """Обратная совместимость: сделка без подписанного договора всё ещё получает отгрузку,
        просто без привязки — как было раньше."""
        deal = multiseller_deal["deal"]
        fulfillment = ensure_fulfillment(deal)
        assert fulfillment.deal_id == deal.id
        assert fulfillment.contract_id is None

    def test_second_call_backfills_a_missing_anchor(self, multiseller_deal):
        """Идемпотентность + дозаполнение: отгрузка могла быть создана ДО появления договора
        (авто-создание идёт раньше). Повторный вызов с договором обязан привязать её, иначе
        исторические записи навсегда останутся в фолбэке."""
        deal, contract = multiseller_deal["deal"], multiseller_deal["contract"]
        first = ensure_fulfillment(deal)
        assert first.contract_id is None

        second = ensure_fulfillment(deal, contract=contract)
        assert second.id == first.id, "создана вторая отгрузка вместо переиспользования"
        assert second.contract_id == contract.id
        assert Fulfillment.objects.filter(deal=deal).count() == 1

    def test_existing_anchor_is_not_overwritten(self, multiseller_deal):
        """Уже привязанную отгрузку повторный вызов не переписывает другим договором."""
        deal, contract = multiseller_deal["deal"], multiseller_deal["contract"]
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
