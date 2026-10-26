"""Журнал кладёт в параметры КОДЫ, а не отображаемые имена.

Событие пишется в момент действия, а читают его позже и, вообще говоря, на другом языке.
Пока сервер клал в `event_params` имя справочника («Черновик») или `get_*_display()`
(«Руководитель»), оно замерзало на языке действовавшего и печаталось всем: в английской ленте
оператора стояло «Deal #16: Черновик → Открытый RFQ» и «Step approved (Руководитель)»
(проход глазами 03-08).

Канон — ARCH-05 «по проводам коды, слова на краях»: сервер шлёт код, подпись подбирает
витрина (`frontend/src/lib/eventText.ts`). Имена остаются рядом ради СТАРЫХ строк, у которых
кода нет, — тест держит именно наличие кодов.
"""

from decimal import Decimal

import pytest

from accounts.constants import Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog, Deal, DealStage, Quote, QuoteStatus
from crm.models.approvals import StepParticipation

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    """Справочники с РУССКИМИ именами — как в проде: именно они и замерзали в журнале."""
    for code, name, order in (("DRAFT", "Черновик", 0), ("RFQ_OPEN", "Открытый RFQ", 25)):
        DealStage.objects.get_or_create(code=code, defaults={"name": name, "sort_order": order})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Покупатель", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    for code in ("DRAFT", "PENDING_APPROVAL", "READY_TO_SEND", "SENT"):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("OWNER", "SALES_MANAGER", "MEMBER"):
        WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def test_stage_change_writes_stage_codes(lookups):
    from crm.services.deals import transition_deal_stage

    company = Company.objects.create(name="Покупатель ООО", inn="7000000001")
    deal = Deal.objects.create(title="Тест", company=company, stage=DealStage.objects.get(code="DRAFT"))
    # Одна позиция: с 20-08 отправка заявки продавцу требует хотя бы одной строки
    # (`REQUEST_HAS_NO_ITEMS`) — раньше гейт жил только в браузере. Тест здесь про КОДЫ в
    # параметрах события, поэтому просто доводим заготовку до состояния, в котором переход законен.
    from crm.models import Quote, QuoteItem

    quote = Quote.objects.create(deal=deal, version=1)
    QuoteItem.objects.create(quote=quote, display_type=QuoteItem.DisplayType.ITEM, quantity=1)

    updated, error = transition_deal_stage(deal=deal, target_stage_code="RFQ_OPEN")

    assert error is None and updated is not None
    params = ActivityLog.objects.get(event_code="deal.stage_changed").event_params
    assert params["from_stage_code"] == "DRAFT"
    assert params["to_stage_code"] == "RFQ_OPEN"
    # Имя остаётся для строк, записанных ДО этой правки, — витрина берёт его как запасной путь.
    assert params["from_stage"] == "Черновик"


def test_approval_step_writes_participation_code(lookups):
    """Роль шага печаталась `get_participation_display()` — переводом на языке согласовавшего."""
    from crm.services.approvals import act_on_step
    from crm.services.quotes import QuoteLifecycleService

    seller = Company.objects.create(name="Продавец ООО", inn="7000000004")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # Визирует исполнитель резолюции (задание расчёта, волна 12 Б1); одобрение директором — маршрут EDS (EDS-03).
    admin_role = CompanyRole.objects.create(company=seller, name="Инженер", permissions=[])
    sales_role = CompanyRole.objects.create(company=seller, name="Продажи", permissions=[Permission.QUOTE_BUILD.value])
    sales_user = _user("sales@codes.test")
    head_user = _user("head@codes.test")
    for user, workspace, role in ((sales_user, "SALES_MANAGER", sales_role), (head_user, "MEMBER", admin_role)):
        CompanyMember.objects.create(
            user=user,
            company=seller,
            role=WorkspaceRole.objects.get(code=workspace),
            company_roles=[role],
            is_primary=True,
            is_active=True,
        )
    buyer = Company.objects.create(name="Покупатель ООО", inn="7000000005")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    deal = Deal.objects.create(
        title="Сделка", company=buyer, manager=sales_user, stage=DealStage.objects.get(code="DRAFT")
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=sales_user,
        subtotal_excl_vat=Decimal("100.00"),
        total_incl_vat=Decimal("112.00"),
    )
    from integration.tests.eds_support import assign_calc

    assign_calc(deal, (head_user, 12, "services"))
    QuoteLifecycleService.submit_for_review(quote.id, sales_user)
    head_step = quote.approval_steps.get(participation=StepParticipation.APPROVER)

    _quote, error = act_on_step(head_step.id, head_user, "APPROVE")

    assert error is None
    params = ActivityLog.objects.get(event_code="quote.approval_step_approved").event_params
    assert params["participation_code"] == "APPROVER"


def test_contract_wording_marks_standard_edition_with_a_code(lookups, monkeypatch):
    """Стандартная редакция отличается от именованного варианта КОДОМ, а не пустой строкой.

    Пустой заголовок читается одинаково и как «выбрана стандартная», и как «вариант без
    названия» — витрине из этого подпись не собрать.
    """
    from crm.services import wording_variants

    captured: dict = {}
    monkeypatch.setattr(
        wording_variants.ActivityLog.objects,
        "create",
        lambda **kwargs: captured.update(kwargs["event_params"]),
    )
    monkeypatch.setattr(wording_variants, "resolve_wording", lambda profile, field: "Стандартный текст")
    monkeypatch.setattr(wording_variants, "_contract_is_signed", lambda contract: False)

    company = Company.objects.create(name="Продавец W", inn="7000000006")
    actor = _user("su@codes.test")
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    deal = Deal.objects.create(title="Сделка W", company=company, stage=DealStage.objects.get(code="DRAFT"))

    _contract, error = wording_variants.select_contract_wording(
        _FakeContract(deal=deal, number="CT-1"), actor, field="contract_liability_text", variant_id=None
    )

    assert error is None
    assert captured["variant_code"] == "STANDARD"
    assert captured["field"] == "contract_liability_text"


class _FakeContract:
    """Договор без БД: тест держит форму `event_params`, а не путь сохранения договора."""

    def __init__(self, *, deal, number):
        self.deal = deal
        self.deal_id = deal.pk
        self.number = number
        self.quote_id = None
        self.quote = None
        self.wording_selections: dict = {}
        self.pdf_file = None

    def save(self, **kwargs):
        return None


class TestBackfillOfOldRows:
    """Миграция `crm/0091` дописывает коды строкам, записанным ДО этой правки.

    Иначе они навсегда остались бы на языке действовавшего: витрине не из чего собрать
    подпись. Прецедент решения — `0086_activity_log_one_word` (владелец, 31-07, вариант «а»).
    """

    @staticmethod
    def _migration():
        from types import SimpleNamespace

        from core.legacy_migration_helpers import backfill_activity_params

        return SimpleNamespace(backfill=backfill_activity_params)

    def test_stage_codes_come_from_the_audit_snapshot_not_from_a_guess(self, lookups):
        from django.apps import apps

        row = ActivityLog.objects.create(
            action="Стадия изменена",
            detail="Сделка #3: Черновик → Открытый RFQ",
            event_code="deal.stage_changed",
            event_params={"deal_id": 3, "from_stage": "Черновик", "to_stage": "Открытый RFQ"},
            before_data={"stage_code": "DRAFT", "stage_name": "Черновик"},
            after_data={"stage_code": "RFQ_OPEN", "stage_name": "Открытый RFQ"},
        )

        self._migration().backfill(apps, None)

        row.refresh_from_db()
        assert row.event_params["from_stage_code"] == "DRAFT"
        assert row.event_params["to_stage_code"] == "RFQ_OPEN"
        assert row.event_code == "deal.stage_changed", "машинный код события неприкосновенен"

    def test_participation_is_reverse_mapped_from_a_closed_set(self, lookups):
        from django.apps import apps

        known = ActivityLog.objects.create(
            action="Шаг согласования пройден",
            event_code="quote.approval_step_approved",
            event_params={"participation": "Руководитель"},
        )
        alien = ActivityLog.objects.create(
            action="Шаг согласования пройден",
            event_code="quote.approval_step_approved",
            event_params={"participation": "Что-то своё"},
        )

        self._migration().backfill(apps, None)

        known.refresh_from_db()
        alien.refresh_from_db()
        assert known.event_params["participation_code"] == "HEAD"
        # Незнакомая подпись не превращается в выдуманный код — строка остаётся как была.
        assert "participation_code" not in alien.event_params

    def test_backfill_is_idempotent_and_never_overwrites(self, lookups):
        from django.apps import apps

        row = ActivityLog.objects.create(
            action="Стадия изменена",
            event_code="deal.stage_changed",
            event_params={"deal_id": 4, "from_stage_code": "SOURCING"},
            before_data={"stage_code": "DRAFT"},
            after_data={"stage_code": "RFQ_OPEN"},
        )

        self._migration().backfill(apps, None)
        self._migration().backfill(apps, None)

        row.refresh_from_db()
        assert row.event_params["from_stage_code"] == "SOURCING", "существующее значение не перезаписывается"
        assert row.event_params["to_stage_code"] == "RFQ_OPEN"
