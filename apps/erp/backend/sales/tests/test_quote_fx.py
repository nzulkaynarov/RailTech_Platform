"""M1-ERP-08 «курс на дату КП» — параметризованные таблицы расчёта и правила снимка курса.

* пересчёт по курсу снимка (база + пошлина) × курс → наценка → скидка, округление до копейки 0.5 вверх;
* КП с позициями в нескольких валютах; снимок хранит курс, дату и источник;
* правило «курса нет» (не старше FX_RATE_MAX_AGE_DAYS) блокирует согласование кодом FX_RATE_MISSING;
* черновик живёт по текущему курсу, фиксация — при отправке на согласование, возврат в черновик
  снова делает курс живым; отправленное КП не меняется от нового курса (пересчёт, акцепт);
* договорной курс финансиста: право finance.rates, причина, журнал, 409 на замороженном, If-Match.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from sales.services.quote_fx import quote_fx_rates
from sales.tests.helpers_fx import build_quote, build_world, currency, send_quote, set_rate

from crm.models import ActivityLog, Quote, QuoteItem, QuoteStatus
from crm.services import QuoteCalculationService
from crm.services.quotes import QuoteLifecycleService, compute_quote_economics

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db):
    return build_world()


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _line(quote):
    return quote.items.order_by("position").first()


# ── 1. Таблица пересчёта по курсу снимка ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "base, duty, qty, rate, margin, discount, landed, final",
    [
        # 100 USD × 12 000 = 1 200 000; наценка 0
        ("100", "0", 1, "12000", "0", "0", "1200000.00", "1200000.00"),
        # наценка 20 % после конвертации
        ("100", "0", 3, "12000", "20", "0", "1200000.00", "1440000.00"),
        # пошлина в валюте строки конвертируется вместе с ценой: (100 + 7.5) × 12 650.5; ×1.2 ×0.9
        ("100", "7.5", 2, "12650.5", "20", "10", "1359928.75", "1468723.05"),
        # округление: 33.33 × 12 650.55 = 421 642.8315 → 421 642.83; ×1.15 = 484 889.2545 → .25
        ("33.33", "0", 1, "12650.55", "15", "0", "421642.83", "484889.25"),
        # половина копейки — вверх (не банковское): 0.01 × 50.5 = 0.505 → 0.51
        ("0.01", "0", 1, "50.5", "0", "0", "0.51", "0.51"),
    ],
)
def test_line_converts_at_snapshot_rate(world, base, duty, qty, rate, margin, discount, landed, final):
    set_rate("USD", rate)
    quote = build_quote(world, [(base, "USD", qty, duty)], margin=margin)
    item = _line(quote)
    if discount != "0":
        item.discount_percent = Decimal(discount)
        item.save()
        item.refresh_from_db()
    assert item.landed_cost == Decimal(landed)
    assert item.final_price_excl_vat == Decimal(final)
    quote.refresh_from_db()
    assert quote.subtotal_excl_vat == (Decimal(final) * qty).quantize(Decimal("0.01"))
    assert Decimal(quote.fx_snapshot["USD"]) == Decimal(rate)


def test_multi_currency_quote_snapshot_with_date_and_source(world):
    usd_date = set_rate("USD", "12650", days_ago=1)
    eur_date = set_rate("EUR", "13700.25", days_ago=2, source="MANUAL")
    quote = build_quote(world, [("100", "USD", 2), ("50", "EUR", 1), ("1000000", "UZS", 1)], margin="0")

    # 2 × 100 × 12 650 + 50 × 13 700.25 + 1 000 000 = 2 530 000 + 685 012.50 + 1 000 000
    assert quote.subtotal_excl_vat == Decimal("4215012.50")
    assert quote.fx_snapshot == {"USD": "12650", "EUR": "13700.25"}
    assert quote.fx_snapshot_meta == {
        "USD": {"rate_date": usd_date.isoformat(), "source": "CBU"},
        "EUR": {"rate_date": eur_date.isoformat(), "source": "MANUAL"},
    }
    rows = {row["currency"]: row for row in quote_fx_rates(quote)}
    assert set(rows) == {"EUR", "USD"}  # UZS — база, строки курса нет
    assert rows["USD"]["rate"] == "12650" and rows["USD"]["rate_date"] == usd_date.isoformat()
    assert rows["EUR"]["source"] == "MANUAL" and rows["EUR"]["missing"] is False


# ── 2. Правило «курса нет» ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "days_ago, missing",
    [(0, False), (3, False), (7, False), (8, True), (-1, True)],
    ids=["today", "weekend-gap", "max-age", "too-old", "future-only"],
)
def test_missing_rate_rule_blocks_submit(world, days_ago, missing):
    set_rate("USD", "12000", days_ago=days_ago)
    quote = build_quote(world, [("100", "USD", 1)])

    economics = compute_quote_economics(quote)
    assert economics["fx_missing"] == (["USD"] if missing else [])
    assert ("USD" in quote.fx_snapshot) is (not missing)

    _quote, err = QuoteLifecycleService.submit_for_review(quote.pk, world.calc)
    assert err == ("FX_RATE_MISSING" if missing else None)


def test_missing_rate_blocks_pdf_render(world):
    quote = build_quote(world, [("100", "USD", 1)])
    with pytest.raises(ValueError, match="FX_RATE_MISSING"):
        QuoteLifecycleService.assert_pdf_renderable(quote.pk)


# ── 3. Живой черновик → фиксация при согласовании → отправленное КП неизменно ────────────────


def test_draft_follows_market_then_fixed_on_submit(world):
    set_rate("USD", "12000", days_ago=1)
    quote = build_quote(world, [("100", "USD", 1)], margin="0")
    assert _line(quote).landed_cost == Decimal("1200000.00")
    assert quote.fx_fixed_at is None

    # Черновик: новый курс ЦБ подхватывается при пересчёте.
    set_rate("USD", "12100")
    QuoteCalculationService.recalculate_quote(quote.pk)
    assert _line(quote).landed_cost == Decimal("1210000.00")

    quote = Quote.objects.get(pk=quote.pk)
    quote.margin_percent = Decimal("20")
    quote.save(update_fields=["margin_percent"])
    QuoteCalculationService.recalculate_quote(quote.pk)
    submitted, err = QuoteLifecycleService.submit_for_review(quote.pk, world.calc)
    assert err is None
    submitted.refresh_from_db()
    assert submitted.fx_fixed_at is not None
    assert submitted.fx_snapshot_meta["USD"]["rate_date"] == timezone.localdate().isoformat()
    assert ActivityLog.objects.filter(entity_type="quote", entity_id=quote.pk, event_code="quote.fx_fixed").exists()

    # После фиксации новый курс ЦБ КП не меняет.
    set_rate("USD", "13000")
    QuoteCalculationService.recalculate_quote(quote.pk)
    assert _line(submitted).landed_cost == Decimal("1210000.00")


def test_submit_refreshes_stale_draft_rate(world):
    set_rate("USD", "12000", days_ago=2)
    quote = build_quote(world, [("100", "USD", 1)], margin="20")
    set_rate("USD", "12500")  # курс обновился, черновик не пересчитывали

    submitted, err = QuoteLifecycleService.submit_for_review(quote.pk, world.calc)
    assert err is None
    assert _line(submitted).landed_cost == Decimal("1250000.00")
    assert submitted.subtotal_excl_vat == Decimal("1500000.00")


def test_return_to_draft_makes_rate_live_again(world):
    from crm.services.approvals import recall_quote

    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)], margin="20")
    submitted, err = QuoteLifecycleService.submit_for_review(quote.pk, world.calc)
    assert err is None
    submitted.refresh_from_db()
    if submitted.status.code == "PENDING_APPROVAL":
        _quote, err = recall_quote(submitted.pk, world.calc)
        assert err is None
    else:  # одиночная цепочка согласована сразу — вернуть в черновик напрямую
        Quote.objects.filter(pk=quote.pk).update(status=QuoteStatus.objects.get(code="DRAFT"), fx_fixed_at=None)
    submitted.refresh_from_db()
    assert submitted.status.code == "DRAFT" and submitted.fx_fixed_at is None

    set_rate("USD", "12300")
    QuoteCalculationService.recalculate_quote(quote.pk)
    assert _line(submitted).landed_cost == Decimal("1230000.00")


def test_sent_quote_immune_to_later_rate_change(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 2), ("250000", "UZS", 1)], margin="20", vat="12")
    sent = send_quote(world, quote)
    sent.refresh_from_db()
    assert sent.status.code == "SENT" and sent.frozen_at is not None
    before = (sent.subtotal_excl_vat, sent.vat_amount, sent.total_incl_vat, dict(sent.fx_snapshot))

    set_rate("USD", "15000")
    QuoteCalculationService.recalculate_quote(sent.pk)
    accepted = QuoteLifecycleService.accept_quote_as_contact(sent.pk, contact_email="buyer@client.test")
    accepted.refresh_from_db()

    assert accepted.status.code == "APPROVED"
    assert (accepted.subtotal_excl_vat, accepted.vat_amount, accepted.total_incl_vat, accepted.fx_snapshot) == before
    assert _line(accepted).landed_cost == Decimal("1200000.00")


def test_new_version_takes_fresh_rate(world):
    from crm.services.quotes.duplicate import duplicate_quote

    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)], margin="20")
    send_quote(world, quote)
    set_rate("USD", "12800")

    copy = duplicate_quote(quote.pk, world.calc)
    copy.refresh_from_db()
    assert copy.version == 2 and copy.fx_snapshot == {"USD": "12800"}
    assert _line(copy).landed_cost == Decimal("1280000.00")


# ── 4. Договорной курс финансиста (fx-override) ─────────────────────────────────────────────


def _override(user, quote, payload, **headers):
    return _api(user).post(f"/api/v1/crm/quotes/{quote.pk}/fx-override/", payload, format="json", **headers)


def test_override_requires_finance_rates_permission(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])
    response = _override(world.calc, quote, {"currency": "USD", "rate": "12500", "reason": "договор"})
    assert response.status_code == 403
    assert response.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_override_wins_logs_reason_and_clears(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)], margin="0")

    response = _override(world.finance, quote, {"currency": "usd", "rate": "12500.5", "reason": "Курс по договору"})
    assert response.status_code == 200, response.json()
    assert _line(quote).landed_cost == Decimal("1250050.00")
    row = next(r for r in response.json()["fx_rates"] if r["currency"] == "USD")
    assert row["source"] == "OVERRIDE" and row["rate"] == "12500.5" and row["snapshot_rate"] == "12000"
    assert row["override"]["reason"] == "Курс по договору"
    log = ActivityLog.objects.get(entity_type="quote", entity_id=quote.pk, event_code="quote.fx_overridden")
    assert log.reason == "Курс по договору" and log.user == world.finance
    assert log.after_data == {"currency": "USD", "rate": "12500.5"}

    response = _override(world.finance, quote, {"currency": "USD", "rate": None, "reason": "Вернули курс ЦБ"})
    assert response.status_code == 200
    assert _line(quote).landed_cost == Decimal("1200000.00")
    assert ActivityLog.objects.filter(entity_id=quote.pk, event_code="quote.fx_override_cleared").exists()


def test_override_unblocks_missing_rate(world):
    quote = build_quote(world, [("100", "CNY", 1)], margin="20")
    assert compute_quote_economics(quote)["fx_missing"] == ["CNY"]
    response = _override(world.finance, quote, {"currency": "CNY", "rate": "1750", "reason": "Курс поставщика"})
    assert response.status_code == 200
    quote.refresh_from_db()
    assert compute_quote_economics(quote)["fx_missing"] == []
    assert _line(quote).landed_cost == Decimal("175000.00")


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"currency": "USD", "rate": "12500", "reason": "  "}, "FX_OVERRIDE_REASON_REQUIRED"),
        ({"currency": "USD", "rate": "12500", "reason": "x" * 501}, None),  # сериализатор: max_length
        ({"currency": "UZS", "rate": "2", "reason": "r"}, "FX_BASE_CURRENCY"),
        ({"currency": "ZZZ", "rate": "2", "reason": "r"}, "FX_CURRENCY_UNKNOWN"),
        ({"currency": "USD", "rate": "0", "reason": "r"}, "FX_RATE_MUST_BE_POSITIVE"),
        ({"currency": "USD", "rate": "-1", "reason": "r"}, "FX_RATE_MUST_BE_POSITIVE"),
        ({"currency": "USD", "rate": "abc", "reason": "r"}, "FX_RATE_INVALID"),
        ({"currency": "USD", "rate": "1.0000001", "reason": "r"}, "FX_RATE_INVALID"),
    ],
)
def test_override_validation(world, payload, code):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])
    response = _override(world.finance, quote, payload)
    assert response.status_code == 400
    if code:
        assert response.json()["detail"] == code
    quote.refresh_from_db()
    assert quote.fx_manual == {}


def test_override_refused_on_sent_quote(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])
    send_quote(world, quote)
    response = _override(world.finance, quote, {"currency": "USD", "rate": "13000", "reason": "поздно"})
    assert response.status_code == 409
    assert response.json()["detail"] == "QUOTE_FROZEN"


def test_override_honours_if_match(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])
    etag = _api(world.finance).get(f"/api/v1/crm/quotes/{quote.pk}/")["ETag"]
    stale = _override(world.finance, quote, {"currency": "USD", "rate": "1", "reason": "r"}, HTTP_IF_MATCH='W/"stale"')
    assert stale.status_code == 412
    fresh = _override(world.finance, quote, {"currency": "USD", "rate": "12100", "reason": "r"}, HTTP_IF_MATCH=etag)
    assert fresh.status_code == 200
    assert fresh["ETag"] != etag


def test_patch_cannot_write_fx_manual(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])
    response = _api(world.calc).patch(f"/api/v1/crm/quotes/{quote.pk}/", {"fx_manual": {"USD": "1"}}, format="json")
    assert response.status_code == 200
    quote.refresh_from_db()
    assert quote.fx_manual == {}
    assert _line(quote).landed_cost == Decimal("1200000.00")


# ── 5. Видимость курса ──────────────────────────────────────────────────────────────────────


def test_fx_rates_visible_only_with_cost_permission(world):
    set_rate("USD", "12000")
    quote = build_quote(world, [("100", "USD", 1)])

    hidden = _api(world.fulfillment).get(f"/api/v1/crm/quotes/{quote.pk}/").json()
    assert "fx_rates" not in hidden and "fx_snapshot" not in hidden
    assert hidden["fx_mode"] == "live"

    shown = _api(world.finance).get(f"/api/v1/crm/quotes/{quote.pk}/").json()
    assert shown["fx_rates"][0]["currency"] == "USD"
    assert shown["fx_rates"][0]["rate_date"] == timezone.localdate().isoformat()


def test_fx_rates_list_missing_line_currency_on_detail(world):
    quote = build_quote(world, [("100", "CNY", 1)])
    data = _api(world.finance).get(f"/api/v1/crm/quotes/{quote.pk}/").json()
    assert data["fx_rates"] == [
        {
            "currency": "CNY",
            "rate": None,
            "rate_date": None,
            "source": None,
            "snapshot_rate": None,
            "snapshot_rate_date": None,
            "snapshot_source": None,
            "override": None,
            "missing": True,
        }
    ]


def test_items_without_currency_count_as_base(world):
    quote = build_quote(world, [("500000", "UZS", 2)], margin="0")
    QuoteItem.objects.filter(quote=quote).update(frozen_currency=None)
    QuoteCalculationService.recalculate_quote(quote.pk)
    quote.refresh_from_db()
    assert quote.subtotal_excl_vat == Decimal("1000000.00")
    assert quote.fx_snapshot == {} and quote_fx_rates(quote) == []
    assert currency("UZS").code == "UZS"
