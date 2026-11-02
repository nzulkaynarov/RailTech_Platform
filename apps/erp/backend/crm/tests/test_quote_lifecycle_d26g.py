"""Находки гейта D2-6: D26G-2 (версия КП после доработки), D26G-3 (клиент отклонил КП), D26G-5 (цена клиенту).

* Повторный «Расчёт готов» после возврата директором — версия КП +1 в ERP, событие `quote.ready_for_approval` несёт её,
  решение EDS по новой версии применяется, по прежней — устаревшее.
* Клиент отклонил КП — экран расчёта и «Мои расчёты» говорят «клиент» и причину; «Новая версия КП» открывает расчёт
  черновиком версии +1 (строки, тип, бригада, резерв), «Отказ по заявке» — стадия «Отказ» и снятый резерв.
* Введённая цена клиенту хранится как есть (500 000 × 500 = 280 000 000 с НДС), введённая наценка — цена из неё,
  округлённая до сума; правка закупки не трогает введённую цену.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone
from integration.tests import bus_support
from inventory.models import Reservation, ReservationStatus

from crm.models import ActivityLog, CalcLine, Deal, Quote, QuoteItem
from crm.services.eds_quote_approval import apply_director_decision
from crm.services.quotes import QuoteCalculationService
from crm.services.quotes._shared import _set_quote_status
from crm.services.quotes.lifecycle_accept import perform_quote_rejection
from crm.tests.test_calc import _api, _priced, _sheet, _started, _url, world  # noqa: F401 — фикстура world

pytestmark = pytest.mark.django_db


def _line(response, item_id):
    return next(line for line in response.json()["lines"] if line["id"] == item_id)


def _single_goods_line(world):  # noqa: F811
    """Расчёт с одной товарной строкой (услуга удалена)."""
    goods_id, service_id = _started(world)
    assert _api(world["engineer"]).delete(_url(world, f"lines/{service_id}/")).status_code == 200
    return goods_id


# ── D26G-5: цена клиенту — источник истины ────────────────────────────────────────────────────────────────────────


def test_entered_client_price_is_kept_exactly_and_the_quote_total_matches(world):  # noqa: F811
    goods_id = _single_goods_line(world)
    supply = _api(world["supply"])
    response = supply.patch(
        _url(world, f"lines/{goods_id}/"),
        {"quantity": 500, "purchase_price": "380000", "client_price": "500000"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert _line(response, goods_id)["client_price"] == "500000.00"
    item = QuoteItem.objects.get(pk=goods_id)
    assert item.final_price_excl_vat == Decimal("500000.00") and item.client_price_fixed == Decimal("500000.00")
    assert item.margin_percent == Decimal("31.58"), "наценка — производная, справочно"
    assert CalcLine.objects.get(item_id=goods_id).price_basis == "client"
    quote = Quote.objects.get(pk=item.quote_id)
    assert quote.subtotal_excl_vat == Decimal("250000000.00")
    assert quote.total_incl_vat == (Decimal("250000000.00") * (1 + quote.vat_rate / 100)).quantize(Decimal("0.01"))
    if quote.vat_rate == Decimal("12.00"):
        assert quote.total_incl_vat == Decimal("280000000.00")

    QuoteCalculationService.recalculate_quote(quote.pk)
    assert QuoteItem.objects.get(pk=goods_id).final_price_excl_vat == Decimal("500000.00"), "пересчёт не трогает"

    # Закупка изменилась — цена клиенту остаётся введённой, наценка пересчитывается.
    response = supply.patch(_url(world, f"lines/{goods_id}/"), {"purchase_price": "400000"}, format="json")
    assert response.status_code == 200, response.json()
    item.refresh_from_db()
    assert item.final_price_excl_vat == Decimal("500000.00") and item.margin_percent == Decimal("25.00")


def test_entered_markup_gives_a_price_rounded_to_whole_sum_that_follows_purchase(world):  # noqa: F811
    goods_id = _single_goods_line(world)
    supply = _api(world["supply"])
    response = supply.patch(
        _url(world, f"lines/{goods_id}/"), {"quantity": 3, "purchase_price": "1000.55"}, format="json"
    )
    assert response.status_code == 200, response.json()
    response = supply.patch(_url(world, f"lines/{goods_id}/"), {"markup_pct": "10"}, format="json")
    assert response.status_code == 200, response.json()
    item = QuoteItem.objects.get(pk=goods_id)
    assert item.final_price_excl_vat == Decimal("1101.00"), "1000,55 × 1,10 = 1100,605 → до сума"
    assert item.margin_percent == Decimal("10.00")
    assert CalcLine.objects.get(item_id=goods_id).price_basis == "markup"

    response = supply.patch(_url(world, f"lines/{goods_id}/"), {"purchase_price": "2000"}, format="json")
    assert response.status_code == 200, response.json()
    item.refresh_from_db()
    assert item.final_price_excl_vat == Decimal("2200.00"), "наценка — источник: цена идёт за закупкой"


def test_price_and_markup_together_are_refused(world):  # noqa: F811
    goods_id = _single_goods_line(world)
    response = _api(world["supply"]).patch(
        _url(world, f"lines/{goods_id}/"), {"client_price": "10", "markup_pct": "10"}, format="json"
    )
    assert response.status_code == 400 and response.json()["markup_pct"] == ["PRICE_OR_MARKUP"]


def test_markup_in_the_quote_builder_drops_the_entered_price(world):  # noqa: F811
    goods_id = _single_goods_line(world)
    _api(world["supply"]).patch(
        _url(world, f"lines/{goods_id}/"), {"purchase_price": "1000", "client_price": "1500"}, format="json"
    )
    from crm.serializers.item import QuoteItemSerializer

    item = QuoteItem.objects.get(pk=goods_id)
    serializer = QuoteItemSerializer(item, data={"margin_percent": "20"}, partial=True)
    assert serializer.is_valid(), serializer.errors
    serializer.save()
    item.refresh_from_db()
    assert item.client_price_fixed is None and item.final_price_excl_vat == Decimal("1200.00")


# ── D26G-2: доработка КП — новая версия в ERP и EDS ───────────────────────────────────────────────────────────────


def _ready(world):  # noqa: F811
    goods_id, service_id = _priced(world)
    assert _api(world["supply"]).post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    assert _api(world["engineer"]).post(_url(world, f"lines/{service_id}/visa/")).status_code == 200
    response = _api(world["supply"]).post(_url(world, "ready/"))
    assert response.status_code == 200, response.json()
    return goods_id, service_id


def _decide(quote, decision, version, comment=None):
    return apply_director_decision(
        erp_quote_id=quote.pk,
        quote_version=version,
        decision=decision,
        route_status={"approve": "approved", "return": "returned", "reject": "rejected"}[decision],
        comment=comment,
        outgoing_number="ИСХ-101/26" if decision == "approve" else None,
        channels=[] if decision == "approve" else None,
        decided_by={"crm_user_id": 3, "full_name": "Директор"},
        decided_at=timezone.now(),
    )


def test_resubmit_after_return_is_version_2_in_erp_and_the_event_and_v2_is_approvable(world):  # noqa: F811
    goods_id, service_id = _ready(world)
    quote = Quote.objects.get(deal=world["deal"])
    assert quote.version == 1
    assert _decide(quote, "return", 1, "Пересчитать цену перевода") == "applied"
    sheet = _sheet(world, world["supply"])
    assert sheet["quote"]["state"] == "returned" and sheet["quote"]["version"] == 1

    supply = _api(world["supply"])
    patched = supply.patch(_url(world, f"lines/{goods_id}/"), {"client_price": "98000000"}, format="json")
    assert patched.status_code == 200, patched.json()
    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    response = supply.post(_url(world, "ready/"))
    assert response.status_code == 200, response.json()
    assert response.json()["quote"]["version"] == 2 and response.json()["quote"]["state"] == "at_director"

    quote.refresh_from_db()
    assert quote.version == 2 and quote.eds_revision == 2 and Quote.objects.filter(deal=world["deal"]).count() == 1
    events = bus_support.published("quote.ready_for_approval")
    assert [e["data"]["payload"]["version"] for e in events] == [1, 2]
    bus_support.assert_matches_contract(events[-1])
    assert events[0]["data"]["payload"]["number"] == events[1]["data"]["payload"]["number"] == quote.number
    superseded = ActivityLog.objects.get(entity_id=quote.pk, event_code="quote.superseded")
    assert superseded.event_params == {"number": quote.number, "version": 1, "new_version": 2}

    assert _decide(quote, "approve", 1) == "stale", "решение по заменённой версии не применяется"
    assert _decide(quote, "approve", 2) == "applied"
    quote.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND" and quote.outgoing_number == "ИСХ-101/26"


# ── D26G-3: клиент отклонил КП ────────────────────────────────────────────────────────────────────────────────────


def _sent_and_rejected(world, reason="Дорого, конкурент дал на 7% ниже"):  # noqa: F811
    goods_id, service_id = _ready(world)
    quote = Quote.objects.get(deal=world["deal"])
    assert _decide(quote, "approve", quote.version) == "applied"
    _set_quote_status(quote, "SENT")
    perform_quote_rejection(quote.pk, reason=reason)
    return quote, goods_id, service_id


def test_client_rejection_says_client_and_reason_and_offers_two_actions(world):  # noqa: F811
    quote, _goods, _service = _sent_and_rejected(world)
    quote.refresh_from_db()
    assert quote.client_reject_reason == "Дорого, конкурент дал на 7% ниже"
    sheet = _sheet(world, world["supply"])
    assert sheet["quote"]["state"] == "rejected" and sheet["quote"]["rejected_by"] == "client"
    assert sheet["quote"]["reject_reason"] == "Дорого, конкурент дал на 7% ниже"
    assert sheet["quote"]["can_revise"] is True
    assert sheet["deal"]["stage_code"] == "CALCULATING", "заявка вернулась в расчёт"
    (row,) = _api(world["supply"]).get("/api/v1/calc/tasks/", {"mine": "1"}).json()["results"]
    assert row["state"] == "rejected" and row["rejected_by"] == "client"
    assert row["reject_reason"] == "Дорого, конкурент дал на 7% ниже"
    assert _sheet(world, world["accountant"])["quote"]["can_revise"] is False, "без quote.build — только просмотр"


def test_director_rejection_is_named_director_and_closes_the_calc(world):  # noqa: F811
    _ready(world)
    quote = Quote.objects.get(deal=world["deal"])
    assert _decide(quote, "reject", 1, "Не наш профиль") == "applied"
    sheet = _sheet(world, world["supply"])
    assert sheet["quote"]["rejected_by"] == "director" and sheet["quote"]["reject_reason"] == "Не наш профиль"
    assert sheet["quote"]["can_revise"] is False
    response = _api(world["supply"]).post(_url(world, "new-version/"))
    assert response.status_code == 409 and response.json()["detail"] == "QUOTE_NOT_REJECTED_BY_CLIENT"


def test_new_version_reopens_the_calc_with_lines_and_crew(world):  # noqa: F811
    quote, goods_id, service_id = _sent_and_rejected(world)
    response = _api(world["supply"]).post(_url(world, "new-version/"))
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["quote"]["version"] == 2 and body["quote"]["state"] == "in_progress"
    assert body["quote"]["rejected_by"] is None and body["quote"]["can_revise"] is False
    assert body["ready"]["blocker"] == "visas_missing", "визы новой версии собираются заново"
    copy = Quote.objects.get(deal=world["deal"], version=2)
    assert copy.status.code == "DRAFT" and copy.number is None
    lines = {line["zone"]: line for line in body["lines"]}
    assert lines["goods"]["client_price"] == "99000000.00" and lines["services"]["crew_rate"] == "1500000.00"
    assert all(line["visa"] is None for line in body["lines"])
    quote.refresh_from_db()
    assert quote.status.code == "REJECTED", "прежняя версия остаётся в истории отклонённой"
    assert ActivityLog.objects.filter(deal=world["deal"], event_code="calc.new_version").exists()
    again = _api(world["supply"]).post(_url(world, "new-version/"))
    assert again.status_code == 409, "вторая копия из той же отклонённой версии не делается"


def test_client_rejection_already_released_the_reservation(world):  # noqa: F811
    """D26G-1: резерв заявки снимается при отказе клиента — до решения менеджера (новая версия резервирует заново)."""
    goods_id, _service_id = _ready(world)
    quote = Quote.objects.get(deal=world["deal"])
    assert _decide(quote, "approve", quote.version) == "applied"
    reservation = Reservation.objects.create(
        product=world["rail"], deal=world["deal"], quote_item_id=goods_id, quantity=1
    )
    _set_quote_status(quote, "SENT")
    perform_quote_rejection(quote.pk, reason="Дорого")
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.RELEASED


def test_lost_after_client_rejection_closes_the_request_and_releases_the_reservation(world):  # noqa: F811
    _quote, goods_id, _service = _sent_and_rejected(world)
    reservation = Reservation.objects.create(
        product=world["rail"], deal=world["deal"], quote_item_id=goods_id, quantity=1
    )
    blank = _api(world["supply"]).post(_url(world, "lost/"), {"reason": "  "}, format="json")
    assert blank.status_code == 400
    response = _api(world["supply"]).post(_url(world, "lost/"), {"reason": "Клиент ушёл к конкуренту"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["deal"]["stage_code"] == "CLOSED_LOST"
    assert Deal.objects.get(pk=world["deal"].pk).stage.code == "CLOSED_LOST"
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.RELEASED
    assert ActivityLog.objects.filter(deal=world["deal"], event_code="calc.lost").exists()
    assert _api(world["supply"]).get("/api/v1/calc/tasks/", {"mine": "1"}).json()["results"] == []


def test_lost_and_new_version_conform_to_the_v1_schema(world):  # noqa: F811
    from core.tests.openapi_fixtures import conforms, sends

    _sent_and_rejected(world)
    base = "/api/v1/calc/{deal_id}/"
    sends(f"{base}lost/", "post", {"reason": "Отказ"})
    conforms(_api(world["supply"]).get(_url(world)), base, "get", status=200)
    conforms(_api(world["supply"]).post(_url(world, "new-version/")), f"{base}new-version/", "post", status=200)
    conforms(
        _api(world["supply"]).post(_url(world, "lost/"), {"reason": "x"}, format="json"),
        f"{base}lost/",
        "post",
        status=409,
    )
