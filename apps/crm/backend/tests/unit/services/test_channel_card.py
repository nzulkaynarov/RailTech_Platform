from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.services.channel_card import (
    CardData,
    can_take,
    duration,
    is_silent,
    needs_sla,
    parse_take,
    products,
    render,
    take_data,
)

CARD = CardData(
    lead_id=124,
    display_name="Азиз <script>",
    language="ru",
    score=75,
    stage="qualified",
    need_summary="интеграция онлайн-кассы с 1С для 3 магазинов",
    product_interest=["pos-integration"],
    timeline="<3m",
    decision_role="decision_maker",
    priority="hot",
    reason_codes=["price_or_contract_asked", "callback_requested"],
    reason_text=None,
    recommendation="позвонить сегодня",
    status="open",
    taken_by=None,
    taken_at=None,
    sla_overdue=False,
    last_lead_message="Ок, пусть позвонят, лучше после 15:00",
    crm_url="https://crm.example.com/leads/124",
)


def test_render_matches_spec_layout() -> None:
    text = render(CARD)
    assert text.splitlines()[0].startswith(
        "🔥 <b>Лид #124</b> · Азиз &lt;script&gt; · RU · Оценка 75 · Квалифицирован"
    )
    assert "Интерес: pos-integration · Срок: до 3 мес. · Роль: ЛПР" in text
    assert "Почему: Цена/условия — нет в базе; Просит звонок" in text
    assert "Рекомендация: позвонить сегодня" in text
    assert "Последнее: 👤 «Ок, пусть позвонят, лучше после 15:00»" in text
    assert "CRM:" not in text
    assert "Номер: не указан" in text  # передача по сигналу бота без номера
    assert can_take(CARD)
    assert "Номер: +998901234567" in render(replace(CARD, phone="+998901234567"))


def test_taken_card_shows_manager_and_local_time() -> None:
    at = datetime(2026, 10, 8, 9, 32, tzinfo=UTC)
    taken = replace(CARD, status="taken", taken_by="Дилшод", taken_at=at, now=at)
    assert "✅ Забрал: Дилшод · 14:32" in render(taken)
    later = replace(taken, now=at + timedelta(days=1))
    assert "✅ Забрал: Дилшод · чт 14:32" in render(later)  # не сегодня — с днём
    assert not can_take(taken)


def test_overdue_and_http_link() -> None:
    card = replace(CARD, sla_overdue=True, crm_url="http://localhost/leads/124")
    text = render(card)
    assert "⏰ <b>Срок реакции просрочен</b>" in text
    assert '<a href="http://localhost/leads/124">открыть</a>' in text


def test_stage_in_words_and_kb_gap_threshold_from_settings() -> None:
    card = replace(CARD, stage="handoff", reason_codes=["kb_gap_streak"], kb_gap_streak=3)
    text = render(card)
    assert text.splitlines()[0].endswith("Оценка 75 · Передан")
    assert "Почему: Бот не нашёл ответ 3 раза подряд" in text
    assert "handoff" not in text
    assert "Score" not in text


NOW = datetime(2026, 10, 12, 9, 32, tzinfo=UTC)  # 14:32 в Ташкенте, понедельник


def test_open_card_shows_waiting_time_and_since() -> None:
    card = replace(CARD, created_at=NOW - timedelta(minutes=12), now=NOW)
    assert "⏳ ждёт 12 мин · с 14:20" in render(card)
    old = replace(CARD, created_at=NOW - timedelta(days=2, hours=3), now=NOW)
    assert "⏳ ждёт 2 д 3 ч · с сб 11:32" in render(old)


def test_snoozed_card_shows_until_and_who() -> None:
    card = replace(
        CARD,
        status="snoozed",
        snoozed_until=NOW + timedelta(minutes=28),
        snoozed_by="Анна",
        now=NOW,
    )
    assert "💤 Отложено до 15:00 · Анна" in render(card)


def test_product_names_without_raw_keys() -> None:
    card = replace(
        CARD,
        product_interest=["pos-integration", "company", "unknown"],
        product_names={"pos-integration": "Интеграция касс"},
        reason_codes=["callback_requested", "weird_code"],
        timeline="??",
    )
    text = render(card)
    assert "Интерес: Интеграция касс" in text
    for raw in ("pos-integration", "company", "unknown", "weird_code", "??"):
        assert raw not in text


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "0 мин"), (59, "59 мин"), (60, "1 ч 0 мин"), (125, "2 ч 5 мин"), (60 * 51, "2 д 3 ч")],
)
def test_duration(minutes: int, expected: str) -> None:
    assert duration(timedelta(minutes=minutes)) == expected


def test_take_data_round_trip_and_legacy() -> None:
    assert parse_take(take_data(15)) == ("escalation", 15)
    assert parse_take("take:7") == ("lead", 7)
    assert parse_take("take:x") is None


def test_silent_and_sla_rules() -> None:
    # передача из-за сбоя ИИ — рабочая карточка в канал: менеджер должен забрать клиента (W15-H3b)
    assert not is_silent(["agent_unavailable"])
    assert not is_silent(["agent_unavailable", "human_requested"])
    assert not is_silent([])
    assert (needs_sla("hot"), needs_sla("warm"), needs_sla("info")) == (True, True, False)
    assert products(["a", "company"], None) == ["a"]
