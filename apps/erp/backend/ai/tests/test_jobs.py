"""Граница ИИ-задачи: трейс по задаче и владельцу, бюджет → код результата, не 500."""

import pytest
from ai.models import AICall, AIJob

from accounts.models import CustomUser
from sourcing.tasks_ai import run_ai_job

JOB_ID = "0b6f2a70-5f8e-4c1d-9f64-8e1f6c2b9a10"


@pytest.fixture
def owner(db):
    user = CustomUser.objects.create_user(email="ai-owner@x.test", username="ai-owner@x.test", password="pw")
    AIJob.objects.create(celery_task_id=JOB_ID, owner=user, feature="compose")
    return user


def _run(feature, payload):
    return run_ai_job.apply(args=[feature, payload], task_id=JOB_ID).get()


@pytest.mark.django_db
def test_job_calls_carry_the_job_session_and_owner(fake_gateway, owner):
    fake_gateway.reply_json({"items": [{"name": "Болт М12", "quantity": 100}]})

    result = _run("compose", {"text": "болты М12, 100 штук"})

    # Без опубликованного каталога сопоставление не зовёт модель (шорт-лист пуст).
    assert [item["name"] for item in result["items"]] == ["Болт М12"]
    metadata = fake_gateway.last_body["metadata"]
    assert metadata["session_id"] == JOB_ID
    assert metadata["trace_user_id"] == f"erp-staff-{owner.id}"
    assert metadata["trace_name"] == "erp.compose"
    row = AICall.objects.get()
    assert (row.session_id, row.user_id) == (JOB_ID, owner.id)


@pytest.mark.django_db
def test_exhausted_budget_is_a_clean_result_code(fake_gateway, owner):
    fake_gateway.reply_budget_exceeded()

    assert _run("preflight", {"lines": [{"name": "болт", "quantity": 1}]}) == {"error": "AI_BUDGET_EXCEEDED"}


@pytest.mark.django_db
def test_gateway_down_is_a_neutral_result_not_a_failure(fake_gateway, owner):
    fake_gateway.reply_transport_error()

    assert _run("preflight", {"lines": [{"name": "болт", "quantity": 1}]}) == {"findings": []}


@pytest.mark.django_db
def test_budget_during_compose_match_keeps_the_lines(fake_gateway, owner, monkeypatch):
    """Бюджет кончился на подсказках каталога — строки запроса не теряются."""
    from ai.services.errors import AIBudgetExceeded

    def _no_budget(*args, **kwargs):
        raise AIBudgetExceeded("erp-ledger")

    monkeypatch.setattr("ai.services.compose.match_lines_to_catalog", _no_budget)
    fake_gateway.reply_json({"items": [{"name": "Кабель ВВГ 3x2,5", "quantity": 50, "unit": "м"}]})

    result = _run("compose", {"text": "кабель ВВГ 3x2,5 — 50 метров"})

    assert result["items"][0]["candidates"] == []
    assert result["items"][0]["quantity"] == 50
