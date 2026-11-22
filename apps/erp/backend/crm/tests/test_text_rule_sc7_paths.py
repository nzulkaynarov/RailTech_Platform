# flake8: noqa: F811  (fixtures are imported from the suites that own them)
"""СЦ-7: the real functions behind the bell and journal texts — not a source grep. Each test calls the function on
factories and applies the shared `assert_human_text` to the stored text."""

from datetime import date

import pytest

from crm.models import ActivityLog, ContractStatus, Deal, DealStage
from crm.tests.test_calc import _api, _started, _url, world  # noqa: F401  (fixtures)
from crm.tests.test_contract_sign_hints import contract_world  # noqa: F401  (fixture)
from notifications.models import Notification
from notifications.tests.human_text import assert_human_text


def test_calc_assigned_bell_names_the_deal_by_number_and_date_dd_mm_yyyy(world):
    """`apply_resolution` (the `world` fixture) notifies the assignees through `_notify_assignee`."""
    deal = world["deal"]
    messages = list(Notification.objects.filter(event_code="deal.calc_assigned").values_list("message", flat=True))
    assert messages, "the resolution must notify its assignees"
    for message in messages:
        assert_human_text(message)
        assert deal.number in message
        assert date(2026, 10, 30).strftime("%d.%m.%Y") in message


@pytest.mark.parametrize("count,word", [(1, "1 строка"), (2, "2 строки"), (5, "5 строк")])
def test_calc_journal_declines_the_lines_word(world, count, word):
    from crm.services import calculation

    quote_rows = [{"product_id": world["rail"].pk, "quantity": 1} for _ in range(count)]
    response = _api(world["supply"]).post(_url(world, "start/"))
    assert response.status_code == 200, response.json()
    added = _api(world["supply"]).post(_url(world, "lines/"), {"lines": quote_rows}, format="json")
    assert added.status_code == 201, added.json()
    detail = ActivityLog.objects.filter(event_code="calc.lines_added").latest("id").detail
    assert_human_text(detail)
    assert detail.startswith(word + " "), detail


def test_calc_copy_journal_declines_the_lines_word(world):
    _started(world)
    other = Deal.objects.create(
        title="Новая заявка",
        company=world["deal"].company,
        manager=world["supply"],
        stage=DealStage.objects.get(code="RFQ_OPEN"),
    )
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal

    from crm.services import calc_tasks

    calc_tasks.apply_resolution(
        other,
        eds_letter_id=uuid.uuid4(),
        letter_number="ВХ-105/26",
        letter_subject="Запрос КП",
        text="Рассчитать",
        due=date(2026, 11, 20),
        min_margin_pct=Decimal("15"),
        decided_by_crm_user_id=3,
        decided_by_name="Директор",
        decided_at=datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc),
        assignees=[calc_tasks.Assignment(11, "goods"), calc_tasks.Assignment(12, "services")],
    )
    response = _api(world["supply"]).post(
        f"/api/v1/calc/{other.pk}/copy/", {"from_deal_id": world["deal"].pk}, format="json"
    )
    assert response.status_code == 201, response.json()
    entry = ActivityLog.objects.filter(detail__contains=world["deal"].number).latest("id")
    assert_human_text(entry.detail)
    assert "1 строка из " + world["deal"].number in entry.detail, entry.detail


def test_contract_signed_bell_names_the_deal_by_number(contract_world):
    from crm.services.contracts import _notify_contract_signed

    contract = contract_world["contract"]
    contract.status = ContractStatus.objects.get(code="SIGNED")
    deal = contract.deal
    deal.client = contract_world["buyer_user"]
    deal.save()
    _notify_contract_signed(contract)
    messages = list(Notification.objects.filter(event_code="contract.signed").values_list("message", flat=True))
    assert messages
    for message in messages:
        assert_human_text(message)
        assert deal.number in message


def test_contract_pending_bell_of_an_untitled_deal_shows_the_number_not_the_id(contract_world):
    from crm.services.contracts import _notify_contract_pending

    contract = contract_world["contract"]
    deal = contract.deal
    deal.title = ""
    deal.client = contract_world["buyer_user"]
    deal.save()
    _notify_contract_pending(contract)
    messages = list(
        Notification.objects.filter(event_code="contract.signature_required").values_list("message", flat=True)
    )
    assert messages
    for message in messages:
        assert_human_text(message)
        assert deal.number in message
