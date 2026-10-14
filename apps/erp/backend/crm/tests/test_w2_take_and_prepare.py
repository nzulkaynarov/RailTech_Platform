"""W2 (spec-inbound-rfq, утв. 27-07): одна кнопка «Взять в работу и подготовить КП».

One-click-quotation (Odoo): claim + стадия CALCULATING + предзаполненный КП одной операцией —
вместо 4–6 ручных шагов на двух экранах. Оркестрация существующих сервисов (claim_deal,
transition_deal_stage FSM, общий builder копии строк). При включённом ИИ (AI_IMPORT_ENABLED) режим
уходит в существующий async job — здесь тестируется маршрутизация режимов и детерминированный путь.
Платный гейт ai.draft (подписка/entitlement) удалён в M1-ERP-02 волна 2: режим решает только то,
включён ли ИИ.
"""

from decimal import Decimal

import pytest

from crm.models import DealStage, Quote, QuoteStatus
from crm.services.draft_quote import prefill_created_quote, take_and_prepare_quote


@pytest.fixture(autouse=True)
def _ai_off_by_default(settings):
    # Local dev may carry an API key → AI_IMPORT_ENABLED=True; the deterministic path is the default here.
    settings.AI_IMPORT_ENABLED = False


@pytest.mark.django_db
def test_one_click_claims_advances_stage_and_prefills_quote(scene):
    """ИИ выключен: claim + RFQ_OPEN→CALCULATING (один FSM-переход) + КП со строками."""
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert result["mode"] == "quote"

    scene["deal"].refresh_from_db()
    assert scene["deal"].assigned_to_id == scene["seller_user"].id  # claim записан на сделку
    assert scene["deal"].assigned_at is not None  # SLA-якорь

    assert scene["deal"].stage.code == "CALCULATING"  # стадия прогнана без Kanban-drag

    quote = result["quote"]
    assert quote.prepared_by_id == scene["seller_user"].id
    items = list(quote.items.all())
    assert len(items) == 2  # строки заявки скопированы — КП не пустой
    matched = next(i for i in items if i.product_id)
    assert matched.frozen_base_price == Decimal("120.00")  # цена из своего оффера, без AI


@pytest.mark.django_db
def test_one_click_is_idempotent(scene):
    first, _ = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    second, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert second["quote"].id == first["quote"].id  # повторный клик не плодит КП v3
    assert Quote.objects.filter(deal=scene["deal"]).count() == 2  # заявка v1 + КП v2


@pytest.mark.django_db
def test_one_click_routes_to_ai_mode_when_ai_is_on(scene, settings):
    settings.AI_IMPORT_ENABLED = True
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert result["mode"] == "ai" and result["quote"] is None  # КП создаст AI-job (view enqueues)
    scene["deal"].refresh_from_db()
    assert scene["deal"].stage.code == "CALCULATING"  # claim+стадия сделаны синхронно уже здесь


@pytest.mark.django_db
def test_one_click_refuses_when_teammate_owns_the_deal(scene):
    take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    result, err = take_and_prepare_quote(scene["deal"].id, scene["teammate"])
    assert result is None
    assert err == "DEAL_ALREADY_CLAIMED"  # чужую работу не перехватываем молча


@pytest.mark.django_db
def test_one_click_refuses_outside_pre_kp_stages(scene):
    scene["deal"].stage = DealStage.objects.get(code="QUOTE_SENT")
    scene["deal"].save()
    result, err = take_and_prepare_quote(scene["deal"].id, scene["seller_user"])
    assert result is None
    assert err == "DEAL_STAGE_NOT_TAKEABLE"  # после отправки КП короткой кнопке делать нечего


@pytest.mark.django_db
def test_manual_quote_create_prefills_request_lines(scene):
    """Разрыв №4: ручной «Сформировать КП» больше не создаёт ПУСТОЙ КП."""
    draft = QuoteStatus.objects.get(code="DRAFT")
    manual = Quote.objects.create(
        deal=scene["deal"],
        version=2,
        status=draft,
        prepared_by=scene["seller_user"],
        seller_company=scene["seller"],
    )
    copied = prefill_created_quote(manual)
    assert copied == 2
    assert manual.items.count() == 2
    # Идемпотентность: непустой КП никогда не дозаполняется повторно.
    assert prefill_created_quote(manual) == 0
    assert manual.items.count() == 2
