"""Авто-цепочка при выигрыше сделки обязана СООБЩАТЬ о несозданном акте.

`auto_invoice_on_closed_won` создаёт счёт в DRAFT, а затем пробует выпустить акт. Но
`generate_act` требует ISSUED/PARTIAL/PAID — то есть по свежесозданному счёту акт не выпустится
никогда. Код возврата присваивался и никуда не шёл: в ответе оставалось `act=None`, в логах
пусто, и «акт не нужен» было не отличить от «акт не создался».

Здесь фиксируется только НАБЛЮДАЕМОСТЬ. Вопрос «когда вообще выпускать акт» продуктовый
(спека post-contract §6) — поведение триггера тестами не закрепляется.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import (
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.tasks import auto_invoice_on_closed_won


@pytest.fixture
def won_deal(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 90})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Pending", "sort_order": 10})

    verified = VerificationStatus.objects.get(code="L2_VERIFIED")
    buyer_co = Company.objects.create(name="Покупатель", inn="AB905", verification_status=verified)
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_co = Company.objects.create(name="Продавец", inn="AS905", verification_status=verified)
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = CustomUser.objects.create_user(email="seller@autoact.test", username="autoact_seller", password="x")
    CompanyMember.objects.create(
        user=seller,
        company=seller_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.now().date() + timedelta(days=30),
    )

    deal = Deal.objects.create(title="Выигранная", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller,
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-AUTOACT-905",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return deal


@pytest.mark.django_db
def test_failed_auto_act_is_reported_in_the_result(won_deal):
    """РЕГРЕСС. Причина несозданного акта обязана попасть в результат таска."""
    result = auto_invoice_on_closed_won(won_deal.id)

    assert result["invoice"] is not None, "счёт не создан — тест проверяет не тот сценарий"
    assert result["act"] is None
    assert result.get("act_error") == "ACT_INVALID_INVOICE_STATUS"


@pytest.mark.django_db
def test_failed_auto_act_is_logged_with_context(won_deal, caplog):
    """В логе должны быть сделка, счёт и его статус — иначе по записи не понять причину."""
    import logging

    with caplog.at_level(logging.WARNING, logger="crm.tasks"):
        auto_invoice_on_closed_won(won_deal.id)

    records = [r for r in caplog.records if "Auto-act skipped" in r.getMessage()]
    assert records, "падение авто-акта по-прежнему проходит молча"
    message = records[0].getMessage()
    assert str(won_deal.id) in message
    assert "ACT_INVALID_INVOICE_STATUS" in message


@pytest.mark.django_db
def test_successful_act_does_not_report_an_error(won_deal):
    """Когда акт создаётся, ключа ошибки в результате быть не должно."""
    from crm.models import Invoice

    auto_invoice_on_closed_won(won_deal.id)
    invoice = Invoice.objects.get(deal=won_deal)
    invoice.status = InvoiceStatus.objects.get(code="ISSUED")
    invoice.save(update_fields=["status"])

    result = auto_invoice_on_closed_won(won_deal.id)
    assert result["act"] is not None
    assert "act_error" not in result
