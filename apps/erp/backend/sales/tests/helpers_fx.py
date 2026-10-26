"""Общий мир для тестов курса на дату КП и отклонения маржи (M1-ERP-08).

Своя компания (продавец) с сотрудниками по системным ролям, компания-клиент с контактом, сделка,
справочник курсов. Только функции — фикстуры собирают их в `sales/tests` и `finance/tests`.
"""

import datetime
from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone
from parties.models import Contact

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services import QuoteCalculationService
from master_data.models import Currency, ExchangeRate


def currency(code):
    return Currency.objects.update_or_create(code=code, defaults={"name": code, "is_active": True})[0]


def set_rate(code, value, *, days_ago=0, source="CBU"):
    """Строка справочника курсов на (сегодня − days_ago)."""
    rate_date = timezone.localdate() - datetime.timedelta(days=days_ago)
    ExchangeRate.objects.update_or_create(
        currency=currency(code), rate_date=rate_date, defaults={"rate_to_uzs": Decimal(str(value)), "source": source}
    )
    return rate_date


def build_world():
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    own = Company.objects.create(name="Своя компания", inn="410000001")
    own.types.add(supplier)
    client = Company.objects.create(name="Клиент", inn="410000002")
    member_role = WorkspaceRole.objects.get(code="MEMBER")
    roles = ensure_default_company_roles(own)

    def staff(email, *role_codes):
        user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
        membership = CompanyMember.objects.create(user=user, company=own, role=member_role, is_primary=True)
        membership.company_roles.add(*[roles[code] for code in role_codes])
        return user

    world = SimpleNamespace(
        own=own,
        client=client,
        calc=staff("calc@own.test", "CALCULATION"),
        finance=staff("fin@own.test", "FINANCE"),
        supply=staff("supply@own.test", "CATALOG_SUPPLY"),
        fulfillment=staff("ful@own.test", "FULFILLMENT"),
        head=staff("head@own.test", "HEAD"),
    )
    contact = Contact.objects.create(company=client, name="Покупатель", email="buyer@client.test")
    world.deal = Deal.objects.create(
        title="Сделка с валютой",
        company=client,
        contact=contact,
        stage=DealStage.objects.get(code="CALCULATING"),
    )
    return world


def build_quote(world, lines, *, margin="20", vat="0", version=1, status="DRAFT"):
    """КП с позициями `lines` = [(цена поставщика, валюта, кол-во[, пошлина])], пересчитанное движком."""
    quote = Quote.objects.create(
        deal=world.deal,
        version=version,
        status=QuoteStatus.objects.get(code=status),
        prepared_by=world.calc,
        seller_company=world.own,
        margin_percent=Decimal(margin),
        vat_rate=Decimal(vat),
    )
    for index, line in enumerate(lines):
        base, code, qty = line[0], line[1], line[2]
        duty = line[3] if len(line) > 3 else "0"
        QuoteItem(
            quote=quote,
            position=index,
            imported_raw_name=f"Позиция {index + 1}",
            quantity=qty,
            frozen_base_price=Decimal(str(base)),
            customs_duty=Decimal(str(duty)),
            frozen_currency=currency(code),
        ).save(skip_recalculate=True)
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()
    return quote


def send_quote(world, quote):
    """Довести КП до отправки клиенту настоящим путём: визы → одобрение директором в EDS (EDS-03) → отправка."""
    from integration.tests.eds_support import approve_in_eds

    from crm.services.approvals import act_on_step
    from crm.services.quotes import QuoteLifecycleService

    submitted, err = QuoteLifecycleService.submit_for_review(quote.pk, world.calc)
    assert err is None, err
    submitted.refresh_from_db()
    for _ in range(10):
        step = (
            submitted.approval_steps.filter(status="PENDING")
            .exclude(participation="INFORMED")
            .order_by("order")
            .first()
        )
        if step is None:
            break
        _quote, err = act_on_step(step.pk, world.head, "APPROVE", "")
        assert err is None, err
        submitted.refresh_from_db()
    assert approve_in_eds(submitted) == "applied"
    submitted.refresh_from_db()
    assert submitted.status.code == "READY_TO_SEND", submitted.status.code
    return QuoteLifecycleService.send_to_client(quote.pk, world.head)
