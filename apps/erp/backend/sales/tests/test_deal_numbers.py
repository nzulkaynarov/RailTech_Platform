"""ERP-09 (W16-D1-2): номер заявки ЗВ-ГГГГ-NNN без пропусков, ПР с тем же NNN после принятия КП, поиск сделок по номеру.

Конкурентность: параллельные создатели сделок получают разные номера подряд — счётчик года берётся `SELECT … FOR UPDATE`.
Мутационная проверка (ORCHESTRATOR §4.1): без `select_for_update` в `deal_numbers._next_seq` тест
`test_parallel_deals_get_distinct_numbers_without_gaps` краснеет (оба потока читают одно значение счётчика, второй
падает на уникальности `(number_year, number_seq)`), с блокировкой — зеленеет; итог — в описании PR.
"""

from __future__ import annotations

import threading
import time

import pytest
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from sales.models import DealNumberCounter
from sales.services import deal_numbers

from crm.constants import DealStageCode
from crm.models import Deal
from crm.services.deals import transition_deal_stage
from crm.views.deals.search import DealSearchFilter

YEAR = timezone.localdate().year


def _deal(title="Заявка"):
    return Deal.objects.create(title=title)


@pytest.mark.django_db
def test_new_deals_get_request_numbers_in_a_row():
    first, second = _deal(), _deal()

    assert first.number == f"ЗВ-{YEAR}-001" and (first.number_year, first.number_seq) == (YEAR, 1)
    assert second.number == f"ЗВ-{YEAR}-002"
    assert DealNumberCounter.objects.get(year=YEAR).last_value == 2


@pytest.mark.django_db
def test_rolled_back_deal_returns_its_number():
    """Без пропусков: откат транзакции создания возвращает номер — следующая заявка получает тот же NNN."""
    _deal()
    with pytest.raises(RuntimeError), transaction.atomic():
        _deal("откатится")
        raise RuntimeError("rollback")

    assert _deal().number == f"ЗВ-{YEAR}-002"


@pytest.mark.django_db
def test_existing_number_is_kept_on_save():
    deal = _deal()
    deal.title = "Новое название"
    deal.save()
    deal.refresh_from_db()
    assert deal.number == f"ЗВ-{YEAR}-001"


@pytest.mark.django_db
@pytest.mark.parametrize("stage", [DealStageCode.CONTRACT_SIGNED, DealStageCode.CLOSED_WON])
def test_project_stage_turns_the_request_into_a_project_with_the_same_number(stage):
    deal = _deal()

    _, error = transition_deal_stage(deal, stage, validate_fsm=False)

    assert error is None
    deal.refresh_from_db()
    assert deal.number == f"ПР-{YEAR}-001" and deal.number_seq == 1
    assert deal_numbers.promote_to_project(deal) is False, "повтор ничего не меняет"


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("ЗВ-2026-104", (2026, 104)),
        ("ПР-2026-104", (2026, 104)),
        ("zv 2026 4", (2026, 4)),
        ("pr-2026-0104", (2026, 104)),
        ("2026-104", (2026, 104)),
        ("КП-2026-104", None),
        ("рельсы", None),
        ("", None),
    ],
)
def test_parse_query(text, parsed):
    assert deal_numbers.parse_query(text) == parsed


class _View:
    search_fields = ["number", "title", "company__name"]


def _search(text):
    request = Request(APIRequestFactory().get("/api/v1/crm/deals/", {"search": text}))
    return list(DealSearchFilter().filter_queryset(request, Deal.objects.order_by("id"), _View()))


@pytest.mark.django_db
def test_search_finds_deals_by_number_under_either_prefix_and_by_title():
    rails = _deal("Рельсы Р65")
    project = _deal("Стрелочные переводы")
    transition_deal_stage(project, DealStageCode.CONTRACT_SIGNED, validate_fsm=False)

    assert _search(f"ЗВ-{YEAR}-002") == [project], "заявка стала проектом — ищется и по старому префиксу"
    assert _search(f"пр {YEAR} 2") == [project]
    assert _search(f"zv-{YEAR}-1") == [rails]
    assert _search("рельсы") == [rails]
    assert _search(f"ЗВ-{YEAR}-777") == []


def _create_in_thread(results, errors, index, barrier):
    try:
        barrier.wait(timeout=10)
        with transaction.atomic():
            results[index] = Deal.objects.create(title=f"Параллельная {index}").number_seq
    except Exception as exc:  # noqa: BLE001 — упавший поток проваливает тест, а не вешает его
        errors.append(exc)
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_parallel_deals_get_distinct_numbers_without_gaps(monkeypatch):
    """Четыре сделки одновременно: номера 1–4 без повторов и пропусков. Между чтением и записью счётчика — пауза,
    чтобы без блокировки потоки гарантированно прочитали одно значение (мутационная проверка)."""
    DealNumberCounter.objects.create(year=YEAR, last_value=0)
    original_save = DealNumberCounter.save

    def slow_save(self, *args, **kwargs):
        time.sleep(0.3)
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(DealNumberCounter, "save", slow_save)
    count = 4
    barrier = threading.Barrier(count)
    results, errors = [None] * count, []
    threads = [threading.Thread(target=_create_in_thread, args=(results, errors, i, barrier)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert sorted(results) == [1, 2, 3, 4]
    assert DealNumberCounter.objects.get(year=YEAR).last_value == 4


@pytest.mark.django_db
def test_0008_numbers_old_deals_by_creation_order_and_sets_the_counter():
    """Миграция 0008 на данных: старые сделки получают NNN по порядку создания в году, проект — префикс ПР."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([("sales", "0007_deal_number_process_auto_send")])
    old = executor.loader.project_state([("sales", "0007_deal_number_process_auto_send")]).apps
    OldDeal = old.get_model("sales", "Deal")
    Stage = old.get_model("sales", "DealStage")
    first = OldDeal.objects.create(title="старая 1")
    second = OldDeal.objects.create(title="старая 2", stage=Stage.objects.get(code="CONTRACT_SIGNED"))

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([("sales", "0008_backfill_deal_numbers")])

    assert Deal.objects.get(pk=first.pk).number == f"ЗВ-{YEAR}-001"
    assert Deal.objects.get(pk=second.pk).number == f"ПР-{YEAR}-002"
    assert DealNumberCounter.objects.get(year=YEAR).last_value == 2
    assert _deal().number == f"ЗВ-{YEAR}-003"
