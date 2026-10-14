"""
Уведомления цепочки согласования КП несут МАШИННЫЙ код (находка 12 прогона 20-08).

Замер 26-08: `_notify_user` создавал `Notification` БЕЗ `event_code`/`event_params`, а вызовы
передавали русские литералы — «Требуется согласование КП», «КП возвращён на доработку», «КП
согласован». Ленту собирает витрина по локали ПОЛУЧАТЕЛЯ (`frontend/src/lib/activityText.ts`:
без кода она печатает сырое поле), поэтому в английском интерфейсе стояли русские строки.

Тот же класс уже чинили волнами #523/#524 — но цепочка внутреннего согласования КП тогда
осталась в стороне: `event_code` в этом файле стоял у `_log()` (ActivityLog), а у
`Notification` — нет. Русский текст сохранён ПОЛЕМ-ФОЛБЭКОМ: он печатается, если для кода нет
перевода, и это лучше пустоты.

Заготовка повторяет `test_quote_approval_chain.py`: та же связка ролей (продавец строит и
подаёт, руководитель согласует) — иначе тест мерил бы не тот путь.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.constants import Permission
from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    WorkspaceRole,
)
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation
from crm.services.approvals import act_on_step
from crm.services.quotes import QuoteLifecycleService as QLS
from master_data.models import Country
from notifications.models import Notification

pytestmark = pytest.mark.django_db

QUOTE_STATUSES = ["DRAFT", "PENDING_TRADE_REVIEW", "PENDING_APPROVAL", "READY_TO_SEND", "SENT", "APPROVED", "REJECTED"]
WORKSPACE_ROLES = ["OWNER", "SALES_MANAGER", "MEMBER"]


@pytest.fixture
def lookups(db):
    for code in QUOTE_STATUSES:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in WORKSPACE_ROLES:
        WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(company, user, *, workspace_role, company_role):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace_role),
        company_role=company_role,
        is_primary=True,
        is_active=True,
        can_sell=False,
    )


@pytest.fixture
def seller(lookups):
    company = Company.objects.create(name="Продавец согласований", inn="908700001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    SupplierSubscription.objects.create(
        company=company, plan="PREMIUM", status="ACTIVE", valid_until=timezone.localdate() + timedelta(days=365)
    )
    admin_role = CompanyRole.objects.create(company=company, name="Администратор компании", is_system=True)
    sales_role = CompanyRole.objects.create(company=company, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])
    sales_user = _user("sales@codes.test")
    _member(company, sales_user, workspace_role="SALES_MANAGER", company_role=sales_role)
    head_user = _user("head@codes.test")
    _member(company, head_user, workspace_role="MEMBER", company_role=admin_role)
    return {"company": company, "sales": sales_user, "head": head_user}


@pytest.fixture
def deal(seller, lookups):
    client_company = Company.objects.create(name="Заказчик", inn="908700002")
    client_company.types.add(CompanyType.objects.get(code="CLIENT"))
    return Deal.objects.create(
        title="Сделка согласований",
        company=client_company,
        manager=seller["sales"],
        stage=DealStage.objects.get(code="DRAFT"),
    )


def _quote(deal, prepared_by):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=prepared_by,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


def _latest(user):
    return Notification.objects.filter(user=user).order_by("-id").first()


def test_the_turn_notification_carries_a_code(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])

    QLS.submit_for_review(quote.id, seller["sales"])

    notification = _latest(seller["head"])
    assert notification is not None, "уведомление обязано появиться — иначе тест зелен по пустоте"
    assert notification.event_code == "quote.approval_your_turn"
    assert notification.event_params.get("number") == (quote.number or quote.id)


def test_the_russian_text_stays_as_a_fallback(seller, deal):
    """Код не заменяет текст, а дополняет его: без перевода лента печатает `title`."""
    quote = _quote(deal, prepared_by=seller["sales"])

    QLS.submit_for_review(quote.id, seller["sales"])

    assert _latest(seller["head"]).title == "Требуется согласование КП"


def test_the_rejection_notification_carries_a_code_and_the_comment(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)

    act_on_step(head_step.id, seller["head"], "REJECT", comment="Слишком дорого")

    notification = _latest(seller["sales"])
    assert notification.event_code == "quote.approval_returned"
    assert notification.event_params.get("comment") == "Слишком дорого"


def test_the_completion_notification_carries_a_code(seller, deal):
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)

    act_on_step(head_step.id, seller["head"], "APPROVE")

    assert _latest(seller["sales"]).event_code == "quote.approval_complete"


def test_no_approval_notification_is_left_without_a_code(seller, deal):
    """Гард против класса: одна забытая ветка возвращает дефект целиком."""
    quote = _quote(deal, prepared_by=seller["sales"])
    QLS.submit_for_review(quote.id, seller["sales"])
    head_step = quote.approval_steps.get(participation=StepParticipation.HEAD)
    act_on_step(head_step.id, seller["head"], "APPROVE")

    codeless = list(Notification.objects.filter(event_code="").values_list("title", flat=True))

    assert codeless == [], f"уведомления без кода: {codeless}"
