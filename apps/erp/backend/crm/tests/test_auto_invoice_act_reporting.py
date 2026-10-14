"""Авто-цепочка при выигрыше сделки: что она создаёт, а что — нет.

История файла. Раньше `auto_invoice_on_closed_won` пробовал выпустить и акт, но вызов был
мёртвым по построению: счёт рождается DRAFT, а `generate_act` требует ISSUED/PARTIAL/PAID.
Сначала (#465) чинилась только НАБЛЮДАЕМОСТЬ — чтобы причина попадала в результат и в лог.

Затем бенчмарк (спека post-contract-open-questions §1) показал, что чинить триггер и не
следовало: ни один эталон не выпускает закрывающий документ в момент подписания сделки. Вызов
удалён (G1), поэтому тесты про «сообщить о падении авто-акта» стали беспредметны — падать
нечему. Здесь остаётся то, что осмысленно: счёт и отгрузка создаются, акт — нет, повторный
прогон идемпотентен. Триггер выпуска акта проверяется в `test_act_trigger_and_due_date.py`.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SupplierSubscription, WorkspaceRole
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
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 90})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Pending", "sort_order": 10})

    buyer_co = Company.objects.create(name="Покупатель", inn="AB905")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_co = Company.objects.create(name="Продавец", inn="AS905")
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
        valid_until=timezone.localdate() + timedelta(days=30),
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
def test_win_creates_the_invoice_and_leaves_the_act_alone(won_deal):
    """Выигрыш сделки заводит счёт-черновик, но не закрывающий документ."""
    result = auto_invoice_on_closed_won(won_deal.id)

    assert result["invoice"] is not None, "счёт не создан — тест проверяет не тот сценарий"
    assert result["act"] is None
    assert "act_error" not in result, "ошибки быть не может: акт здесь больше не выпускается"


@pytest.mark.django_db
def test_no_act_error_is_logged_anymore(won_deal, caplog):
    """Раньше каждый выигрыш сделки писал в лог предупреждение о «пропущенном» акте.

    Это был шум от вызова, который не мог сработать в принципе. Теперь его нет.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="crm.tasks"):
        auto_invoice_on_closed_won(won_deal.id)

    assert not [r for r in caplog.records if "Auto-act skipped" in r.getMessage()]


@pytest.mark.django_db
def test_rerun_reports_an_act_issued_by_hand(won_deal):
    """Акт, выпущенный продавцом вручную, отражается в отчёте повторного прогона —
    задача остаётся наблюдаемой."""
    from crm.models import Act, Invoice

    auto_invoice_on_closed_won(won_deal.id)
    invoice = Invoice.objects.get(deal=won_deal)
    act = Act.objects.create(
        deal=won_deal,
        invoice=invoice,
        number="ACT-AUTOACT-905",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )

    result = auto_invoice_on_closed_won(won_deal.id)

    assert result["act"] == act.id
    assert result["idempotent_reuse"] is True
