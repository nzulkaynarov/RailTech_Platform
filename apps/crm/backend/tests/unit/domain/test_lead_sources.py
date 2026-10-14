"""Источники лидов и склейка по номеру (M3-CRM-05, ARCHITECTURE §17): таблицы кейсов."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.lead_sources import (
    MANUAL_SOURCES,
    LeadFacts,
    LeadSource,
    merge_plan,
    normalize_phone_e164,
)
from app.domain.stages import Stage

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123-45-67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("00998901234567", "+998901234567"),
        ("90 123 45 67", "+998901234567"),
        ("(90) 123-45-67", "+998901234567"),
        ("+7 999 123 45 67", "+79991234567"),
        ("+1 650 555 0100", "+16505550100"),
        ("  +998901234567  ", "+998901234567"),
        ("", None),
        ("   ", None),
        (None, None),
        ("abc", None),
        ("12345", None),
        ("+0998901234567", None),
        ("+998 90 123-45-67 доб. 12", None),
    ],
)
def test_normalize_phone_e164(raw: str | None, expected: str | None) -> None:
    assert normalize_phone_e164(raw) == expected


def test_sources() -> None:
    assert {s.value for s in LeadSource} == {"telegram", "web", "phone", "email", "referral"}
    assert {LeadSource.PHONE, LeadSource.EMAIL, LeadSource.REFERRAL} == MANUAL_SOURCES
    assert LeadSource.TELEGRAM not in MANUAL_SOURCES
    assert LeadSource.WEB not in MANUAL_SOURCES


def facts(**patch: Any) -> LeadFacts:
    base: dict[str, Any] = {
        "id": 1,
        "created_at": T0,
        "source": "web",
        "stage": "new",
    }
    base.update(patch)
    return LeadFacts(**base)


# Лид с номером (web/phone/email/referral) создан раньше; позже тот же человек написал в бот и
# поделился номером — Telegram-лид (id 2, created позже) склеивается с первым.
WEB = facts(
    id=1,
    source="web",
    stage="new",
    owner_mode="paused",
    display_name="Алишер",
    company_name="ООО Рельс",
    email="a@rail.uz",
    phone_e164="+998901234567",
    need_summary="Нужна интеграция POS",
)
TG = facts(
    id=2,
    created_at=T1,
    source="telegram",
    stage="qualified",
    score=55,
    owner_mode="bot",
    language="uz",
    language_confirmed=True,
    display_name="alisher",
    consent_given_at=T1,
    product_interest=("pos-integration",),
    qualification={"timeline": "<3m", "company": "Rels"},
)


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        pytest.param(
            WEB,
            TG,
            {
                "survivor_id": 1,
                "absorbed_id": 2,
                "source": "web",
                "stage": Stage.QUALIFIED,
                "stage_changed": True,
                "score": 55,
                "owner_mode": "paused",
                "assigned_user_id": None,
                "language": "uz",
                "language_confirmed": True,
                "display_name": "Алишер",
                "need_summary": "Нужна интеграция POS",
                "consent_given_at": T1,
                "product_interest": ("pos-integration",),
                "qualification": {"timeline": "<3m", "company": "Rels"},
                "company_name": "ООО Рельс",
                "email": "a@rail.uz",
                "phone_e164": "+998901234567",
                "close_absorbed_escalation": False,
            },
            id="web-first-then-telegram: one card, source web, stage raised, identity kept",
        ),
        pytest.param(
            TG,
            WEB,
            {"survivor_id": 1, "absorbed_id": 2, "source": "web", "stage": Stage.QUALIFIED},
            id="order of arguments does not matter: earlier card survives",
        ),
        pytest.param(
            facts(id=1, source="telegram", stage="engaged", created_at=T0),
            facts(
                id=2,
                source="phone",
                stage="in_progress",
                created_at=T1,
                owner_mode="human",
                assigned_user_id=7,
            ),
            {
                "survivor_id": 1,
                "source": "telegram",
                "stage": Stage.IN_PROGRESS,
                "stage_changed": True,
                "owner_mode": "human",
                "assigned_user_id": 7,
            },
            id="telegram-first then manual (taken by manager): manager keeps the lead",
        ),
        pytest.param(
            facts(id=1, stage="in_progress", owner_mode="human", assigned_user_id=3),
            facts(id=2, created_at=T1, source="telegram", stage="new", owner_mode="bot"),
            {"stage": Stage.IN_PROGRESS, "stage_changed": False, "assigned_user_id": 3},
            id="stage is never lowered; survivor's owner wins",
        ),
        pytest.param(
            facts(id=1, stage="lost"),
            facts(id=2, created_at=T1, source="telegram", stage="engaged"),
            {"stage": Stage.ENGAGED, "stage_changed": True},
            id="lost lead that wrote again comes back to engaged",
        ),
        pytest.param(
            facts(id=1, stage="customer", client_id=9),
            facts(id=2, created_at=T1, source="telegram", stage="engaged"),
            {"stage": Stage.CUSTOMER, "stage_changed": False, "client_id": 9},
            id="customer stays customer and keeps client link",
        ),
        pytest.param(
            facts(id=1, stage="new", has_open_escalation=True, owner_mode="paused"),
            facts(
                id=2,
                created_at=T1,
                source="telegram",
                stage="handoff",
                has_open_escalation=True,
                owner_mode="paused",
            ),
            {"stage": Stage.HANDOFF, "close_absorbed_escalation": True},
            id="two open handoffs: absorbed one is closed (unique open escalation per lead)",
        ),
        pytest.param(
            facts(id=1, has_open_escalation=False),
            facts(
                id=2, created_at=T1, source="telegram", stage="handoff", has_open_escalation=True
            ),
            {"close_absorbed_escalation": False},
            id="only absorbed has a handoff: it moves to the survivor",
        ),
        pytest.param(
            facts(id=5, created_at=T1, source="telegram", stage="new"),
            facts(id=9, created_at=T1, source="referral", stage="new"),
            {"survivor_id": 5, "absorbed_id": 9, "source": "telegram"},
            id="same created_at: lower id is the first one",
        ),
        pytest.param(
            facts(id=1, language="ru", language_confirmed=False, display_name=""),
            facts(
                id=2,
                created_at=T1,
                source="telegram",
                stage="new",
                language="en",
                language_confirmed=True,
                display_name="John",
            ),
            {"language": "en", "language_confirmed": True, "display_name": "John"},
            id="confirmed language and the only non-empty name win",
        ),
        pytest.param(
            facts(id=1, language="ru", language_confirmed=True),
            facts(
                id=2,
                created_at=T1,
                source="telegram",
                stage="new",
                language="en",
                language_confirmed=True,
            ),
            {"language": "ru"},
            id="both confirmed: survivor's language",
        ),
        pytest.param(
            facts(
                id=1, consent_given_at=T1, qualification={"company": "A"}, product_interest=("a",)
            ),
            facts(
                id=2,
                created_at=T1,
                source="telegram",
                stage="new",
                consent_given_at=T0,
                qualification={"company": "B", "region": "Tashkent"},
                product_interest=("b", "a"),
            ),
            {
                "consent_given_at": T0,
                "qualification": {"company": "A", "region": "Tashkent"},
                "product_interest": ("a", "b"),
            },
            id="earliest consent, qualification complemented not overwritten, interests united",
        ),
    ],
)
def test_merge_plan(existing: LeadFacts, incoming: LeadFacts, expected: dict[str, Any]) -> None:
    plan = merge_plan(existing, incoming)
    for key, value in expected.items():
        assert getattr(plan, key) == value, key
