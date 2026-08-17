"""Непокрытые пути биллинга: фиксация платежа, выпуск и подписание акта.

`crm/services/billing.py` был покрыт на 55%. Дыры приходились ровно на деньги на входе и
на акт: идемпотентность платежа по банковской ссылке (двойной клик не должен зачесть
платёж дважды), переход инвойса в частично оплаченный, гейты оператора-наблюдателя, и —
существенное — запрет продавцу выпускать акт по инвойсу КОНКУРЕНТА (аудит H4).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

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
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)
from crm.services._params import PaymentData
from crm.services.billing import generate_act, generate_invoice_from_contract, record_payment, sign_act


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    for code in ("DRAFT", "CONTRACT_SIGNED", "CLOSED_WON"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


@pytest.fixture
def world(lookups):
    """Покупатель, зароутиненный продавец с подпиской, ПОСТОРОННИЙ продавец и подписанный
    договор, готовый к выставлению счёта."""
    buyer_co = _company("Покупатель", "B902", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@billpaths.test", can_buy=True)

    seller_co = _company("Продавец", "S902", "SUPPLIER")
    seller_user = _member(seller_co, "seller@billpaths.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )

    other_co = _company("Посторонний продавец", "O902", "SUPPLIER")
    other_user = _member(other_co, "other@billpaths.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=other_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )

    operator = CustomUser.objects.create_user(
        email="operator@billpaths.test",
        username="operator@billpaths.test",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
    )

    deal = Deal.objects.create(title="Сделка", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller_user,
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-BILLPATHS-902",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "buyer_user": buyer_user,
        "seller_user": seller_user,
        "other_user": other_user,
        "operator": operator,
        "deal": deal,
        "contract": contract,
    }


def _issued_invoice(world):
    """Выставленный счёт на 112 — живая дебиторка, против которой можно платить."""
    invoice, error = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert error is None, error
    invoice.status = InvoiceStatus.objects.get(code="ISSUED")
    invoice.save(update_fields=["status"])
    return invoice


# ── Деньги на входе ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRecordPaymentGates:
    def test_platform_admin_viewer_cannot_record(self, world):
        """Оператор платформы не действует от имени компании (ADR-0002)."""
        invoice = _issued_invoice(world)
        result, error = record_payment(invoice.id, actor=world["operator"], amount=Decimal("10"), paid_at=date.today())
        assert result is None
        assert error == "ADMIN_VIEWER_CANNOT_ACT"

    def test_seller_cannot_record_buyers_payment(self, world):
        """Платёж фиксирует покупательская сторона сделки."""
        invoice = _issued_invoice(world)
        result, error = record_payment(
            invoice.id, actor=world["seller_user"], amount=Decimal("10"), paid_at=date.today()
        )
        assert result is None
        assert error == "MEMBER_REQUIRED_FOR_ACTION"

    def test_missing_invoice_is_reported(self, world):
        result, error = record_payment(10**7, actor=world["buyer_user"], amount=Decimal("10"), paid_at=date.today())
        assert result is None
        assert error == "NOT_FOUND"

    def test_cancelled_invoice_takes_no_money(self, world):
        invoice = _issued_invoice(world)
        invoice.status = InvoiceStatus.objects.get(code="CANCELLED")
        invoice.save(update_fields=["status"])
        result, error = record_payment(
            invoice.id, actor=world["buyer_user"], amount=Decimal("10"), paid_at=date.today()
        )
        assert result is None
        assert error == "INVOICE_CANCELLED"

    @pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-5")])
    def test_non_positive_amount_is_rejected(self, world, amount):
        """Ноль и отрицательная сумма — не платёж; иначе в реестр попадёт мусорная строка."""
        invoice = _issued_invoice(world)
        result, error = record_payment(invoice.id, actor=world["buyer_user"], amount=amount, paid_at=date.today())
        assert result is None
        assert error == "PAYMENT_AMOUNT_MUST_BE_POSITIVE"
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("0")


@pytest.mark.django_db
class TestRecordPaymentAccounting:
    def test_partial_payment_moves_invoice_to_partial(self, world):
        """Недоплата НЕ закрывает счёт: он становится частично оплаченным."""
        invoice = _issued_invoice(world)
        payment, error = record_payment(
            invoice.id, actor=world["buyer_user"], amount=Decimal("50"), paid_at=date.today()
        )
        assert error is None
        assert payment.amount == Decimal("50")
        invoice.refresh_from_db()
        assert invoice.status_code == "PARTIAL"
        assert invoice.amount_paid == Decimal("50")

    def test_payments_accumulate_until_paid(self, world):
        """Две частичные оплаты складываются и закрывают счёт ровно на полной сумме."""
        invoice = _issued_invoice(world)
        record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("50"), paid_at=date.today())
        record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("62"), paid_at=date.today())
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("112")
        assert invoice.status_code == "PAID"

    def test_fully_paid_invoice_takes_no_more(self, world):
        """Переплаты быть не должно."""
        invoice = _issued_invoice(world)
        record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("112"), paid_at=date.today())
        result, error = record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("1"), paid_at=date.today())
        assert result is None
        assert error == "INVOICE_ALREADY_PAID"

    def test_same_bank_reference_is_not_counted_twice(self, world):
        """ГЛАВНОЕ. Банковская ссылка однозначно опознаёт реальный платёж: повторная отправка
        (двойной клик, ретрай сети) обязана вернуть УЖЕ созданную запись, а не зачесть деньги
        второй раз."""
        invoice = _issued_invoice(world)
        first, error = record_payment(
            invoice.id, actor=world["buyer_user"], amount=Decimal("50"), paid_at=date.today(), reference="PP-77"
        )
        assert error is None

        second, error = record_payment(
            invoice.id, actor=world["buyer_user"], amount=Decimal("50"), paid_at=date.today(), reference="PP-77"
        )
        assert error is None
        assert second.id == first.id, "повторная отправка создала ВТОРОЙ платёж"

        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("50"), "деньги зачтены дважды"
        assert Payment.objects.filter(invoice=invoice).count() == 1

    def test_empty_reference_does_not_deduplicate(self, world):
        """Без ссылки дедупликация невозможна — два платежа без неё остаются двумя."""
        invoice = _issued_invoice(world)
        record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("30"), paid_at=date.today())
        record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("30"), paid_at=date.today())
        invoice.refresh_from_db()
        assert Payment.objects.filter(invoice=invoice).count() == 2
        assert invoice.amount_paid == Decimal("60")

    def test_payment_data_dataclass_is_accepted(self, world):
        """Новый путь вызова через PaymentData должен давать тот же результат, что и аргументы."""
        invoice = _issued_invoice(world)
        payment, error = record_payment(
            PaymentData(
                invoice_id=invoice.id,
                amount=Decimal("112"),
                paid_at=date.today(),
                method="CARD",
                reference="PD-1",
            ),
            actor=world["buyer_user"],
        )
        assert error is None
        assert (payment.method, payment.reference) == ("CARD", "PD-1")
        invoice.refresh_from_db()
        assert invoice.status_code == "PAID"


# ── Акт: выпуск и подписание ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestGenerateAct:
    def test_platform_admin_viewer_cannot_issue(self, world):
        invoice = _issued_invoice(world)
        result, error = generate_act(invoice.id, actor=world["operator"])
        assert result is None
        assert error == "ADMIN_VIEWER_CANNOT_ACT"

    def test_buyer_cannot_issue_the_act(self, world):
        """Акт выпускает продавецкая сторона."""
        invoice = _issued_invoice(world)
        result, error = generate_act(invoice.id, actor=world["buyer_user"])
        assert result is None
        assert error == "MEMBER_REQUIRED_FOR_ACTION"

    def test_competitor_seller_cannot_issue_act_on_foreign_invoice(self, world):
        """Аудит H4 — граница конфиденциальности: продавец, не зароутиненный на сделку, не
        должен выпускать акт по чужому счёту."""
        invoice = _issued_invoice(world)
        result, error = generate_act(invoice.id, actor=world["other_user"])
        assert result is None
        assert error == "MEMBER_REQUIRED_FOR_ACTION"

    def test_draft_invoice_cannot_produce_an_act(self, world):
        """Акт — против живого счёта, а не против черновика."""
        invoice, error = generate_invoice_from_contract(world["contract"].id, actor=None)
        assert error is None
        assert invoice.status_code == "DRAFT"
        result, error = generate_act(invoice.id, actor=world["seller_user"])
        assert result is None
        assert error == "ACT_INVALID_INVOICE_STATUS"

    def test_missing_invoice_is_reported(self, world):
        result, error = generate_act(10**7, actor=world["seller_user"])
        assert result is None
        assert error == "NOT_FOUND"

    def test_routed_seller_issues_an_act_mirroring_the_invoice(self, world):
        """Акт зеркалит счёт: та же сумма, статус «выпущен», связи проставлены."""
        invoice = _issued_invoice(world)
        act, error = generate_act(invoice.id, actor=world["seller_user"])
        assert error is None
        assert act.status_code == "ISSUED"
        assert act.total_amount == invoice.total_incl_vat
        assert (act.invoice_id, act.deal_id) == (invoice.id, world["deal"].id)
        assert act.number


@pytest.mark.django_db
class TestSignAct:
    def _issued_act(self, world):
        invoice = _issued_invoice(world)
        act, error = generate_act(invoice.id, actor=world["seller_user"])
        assert error is None
        return act

    def test_platform_admin_viewer_cannot_sign(self, world):
        act = self._issued_act(world)
        result, error = sign_act(act.id, actor=world["operator"])
        assert result is None
        assert error == "ADMIN_VIEWER_CANNOT_ACT"

    def test_signing_stamps_status_and_time(self, world):
        act = self._issued_act(world)
        signed, error = sign_act(act.id, actor=world["buyer_user"])
        assert error is None
        assert signed.status_code == "SIGNED"
        assert signed.signed_at is not None

    def test_already_signed_act_cannot_be_signed_again(self, world):
        act = self._issued_act(world)
        sign_act(act.id, actor=world["buyer_user"])
        result, error = sign_act(act.id, actor=world["buyer_user"])
        assert result is None
        assert error == "ACT_SIGN_NOT_ALLOWED"

    def test_cancelled_act_cannot_be_signed(self, world):
        act = self._issued_act(world)
        act.status = ActStatus.objects.get(code="CANCELLED")
        act.save(update_fields=["status"])
        result, error = sign_act(act.id, actor=world["buyer_user"])
        assert result is None
        assert error == "ACT_SIGN_NOT_ALLOWED"

    def test_signing_is_logged_as_manual(self, world):
        """[MANUAL_MODE] — отметка, что это клик, а не квалифицированная ЭЦП; по ней потом
        отделят такие записи от настоящих подписей E-IMZO."""
        from crm.models import ActivityLog

        act = self._issued_act(world)
        sign_act(act.id, actor=world["buyer_user"])
        entry = ActivityLog.objects.filter(event_code="act.signed").order_by("-id").first()
        assert entry is not None
        assert entry.action.startswith("[MANUAL_MODE]")
        assert entry.event_params["manual"] is True


@pytest.mark.django_db
def test_act_model_is_reachable_from_invoice(world):
    """Связка счёт → акт: реестр актов строится по ней."""
    invoice = _issued_invoice(world)
    generate_act(invoice.id, actor=world["seller_user"])
    assert Act.objects.filter(invoice=invoice).count() == 1
