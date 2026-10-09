from dataclasses import replace
from datetime import UTC, datetime

from app.services.channel_card import CardData, can_take, render

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
        "🔥 <b>Лид #124</b> · Азиз &lt;script&gt; · RU · Score 75"
    )
    assert "Интерес: pos-integration · Срок: &lt;3 мес · Роль: ЛПР" in text
    assert "Почему: спросил цену/условия — нет в базе; просит звонок" in text
    assert "Рекомендация: позвонить сегодня" in text
    assert "Последнее: 👤 «Ок, пусть позвонят, лучше после 15:00»" in text
    assert "CRM:" not in text
    assert can_take(CARD)


def test_taken_card_shows_manager_and_local_time() -> None:
    taken = replace(
        CARD, status="taken", taken_by="Дилшод", taken_at=datetime(2026, 10, 8, 9, 32, tzinfo=UTC)
    )
    assert "✅ Взял: Дилшод · 14:32" in render(taken)
    assert not can_take(taken)


def test_overdue_and_http_link() -> None:
    card = replace(CARD, sla_overdue=True, crm_url="http://localhost/leads/124")
    text = render(card)
    assert "⏰ <b>SLA просрочен</b>" in text
    assert "CRM: http://localhost/leads/124" in text
