"""Клиент шлюза LiteLLM: тело вызова, теги расходов, трейс, ошибки, бюджет, журнал (M1-ERP-06)."""

from decimal import Decimal

import pytest
from ai.models import AICall
from ai.services.context import trace_scope
from ai.services.errors import AI_GATEWAY_ERROR, AI_GATEWAY_UNAVAILABLE, AIBudgetExceeded
from ai.services.gateway import FEATURE_ALIASES, JsonCall, alias_for, call_json, text_block, trace_id_for
from ai.services.prompts import load_prompt

SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}


def _call(feature="compose", **overrides):
    prompt = load_prompt("compose")
    params = {
        "feature": feature,
        "prompt": prompt,
        "system": prompt.render(),
        "user_content": [text_block("нужны болты М12, 100 шт")],
        "schema": SCHEMA,
        "max_tokens": 100,
    }
    params.update(overrides)
    return JsonCall(**params)


@pytest.mark.django_db
def test_body_carries_alias_tags_and_structured_output(fake_gateway):
    fake_gateway.reply_json({"items": []}, cost="0.000321")

    result = call_json(_call())

    assert result.ok and result.data == {"items": []}
    request = fake_gateway.requests[0]
    assert request["url"] == "http://litellm.test/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-erp-test"
    body = request["body"]
    assert body["model"] == "intake-model"
    assert body["metadata"]["tags"] == ["system=erp", "feature=compose", "model=intake-model"]
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["response_format"]["json_schema"]["strict"] is True
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert result.usage.cost_usd == Decimal("0.000321")


@pytest.mark.django_db
def test_trace_metadata_comes_from_the_job_scope_not_the_model(fake_gateway):
    fake_gateway.reply_json({"items": []})
    job_id = "6f1c1f0e-3a54-4d4b-9a59-2f0b1b7c9d11"

    with trace_scope(job_id, user_id=42, job_feature="draft_quote") as trace:
        call_json(_call(feature="match"))

    metadata = fake_gateway.last_body["metadata"]
    assert metadata["session_id"] == job_id
    assert metadata["trace_id"] == trace_id_for(job_id) == job_id.replace("-", "")
    assert metadata["trace_user_id"] == "erp-staff-42"
    assert metadata["trace_name"] == "erp.draft_quote"
    assert metadata["generation_name"] == "erp.match"
    prompt = load_prompt("compose")
    assert metadata["trace_metadata"]["prompt_version"] == prompt.version
    assert trace.calls == 1 and trace.prompt_versions == {"compose": prompt.version}


@pytest.mark.django_db
def test_every_call_lands_in_the_ledger_with_prompt_version(fake_gateway):
    fake_gateway.reply_json({"items": []}, cost="0.002", tokens=(120, 30))

    with trace_scope("job-1", user_id=7):
        call_json(_call())

    row = AICall.objects.get()
    assert (row.session_id, row.user_id, row.feature, row.model_alias) == ("job-1", 7, "compose", "intake-model")
    assert row.prompt_name == "compose" and row.prompt_version == load_prompt("compose").version
    assert (row.status, row.input_tokens, row.output_tokens, row.cost_usd) == ("ok", 120, 30, Decimal("0.002"))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arrange, status, code",
    [
        (lambda gw: gw.reply_transport_error(), "error", AI_GATEWAY_UNAVAILABLE),
        (lambda gw: gw.reply_http_error(500), "error", AI_GATEWAY_ERROR),
        (lambda gw: gw.reply_http_error(400, "invalid_request_error"), "error", AI_GATEWAY_ERROR),
        (lambda gw: gw.reply_refusal(), "refusal", ""),
        (lambda gw: gw.reply_text("not json at all"), "invalid_json", "AI_BAD_RESPONSE"),
        (lambda gw: gw.reply_text('{"items": [', finish_reason="length"), "truncated", "AI_BAD_RESPONSE"),
        (lambda gw: gw.reply_text('["a list, not an object"]'), "invalid_json", "AI_BAD_RESPONSE"),
    ],
)
def test_failures_are_logged_noops_not_exceptions(fake_gateway, arrange, status, code):
    arrange(fake_gateway)

    result = call_json(_call())

    assert (result.status, result.error_code, result.data) == (status, code, None)
    assert not result.ok
    assert AICall.objects.get().status == status


@pytest.mark.django_db
def test_fenced_json_is_accepted(fake_gateway):
    fake_gateway.reply_text('```json\n{"items": [1]}\n```')
    assert call_json(_call()).data == {"items": [1]}


@pytest.mark.django_db
def test_gateway_key_budget_is_raised_as_budget_exceeded(fake_gateway):
    fake_gateway.reply_budget_exceeded()

    with pytest.raises(AIBudgetExceeded):
        call_json(_call())

    assert AICall.objects.get().status == "budget"


@pytest.mark.django_db
def test_erp_daily_budget_stops_before_the_call(fake_gateway, settings):
    settings.AI_DAILY_BUDGET_USD = 0.01
    AICall.objects.create(
        session_id="earlier",
        feature="compose",
        model_alias="intake-model",
        prompt_name="compose",
        prompt_version="x",
        status="ok",
        cost_usd=Decimal("0.0100"),
    )

    with pytest.raises(AIBudgetExceeded):
        call_json(_call())

    assert fake_gateway.calls == 0, "бюджет исчерпан — вызова к шлюзу нет"


@pytest.mark.django_db
def test_budget_counts_only_today(fake_gateway, settings):
    from datetime import timedelta

    from django.utils import timezone

    settings.AI_DAILY_BUDGET_USD = 0.01
    old = AICall.objects.create(
        session_id="yesterday",
        feature="compose",
        model_alias="intake-model",
        prompt_name="compose",
        prompt_version="x",
        status="ok",
        cost_usd=Decimal("5"),
    )
    AICall.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1, hours=1))
    fake_gateway.reply_json({"items": []})

    assert call_json(_call()).ok


def test_disabled_ai_makes_no_call(settings):
    settings.AI_IMPORT_ENABLED = False
    result = call_json(_call())
    assert (result.status, result.error_code) == ("disabled", AI_GATEWAY_UNAVAILABLE)


def test_every_feature_maps_to_an_erp_alias():
    assert set(FEATURE_ALIASES.values()) == {"intake-model", "match-model", "draft-model", "enrich-model"}
    with pytest.raises(KeyError):
        alias_for("unknown-feature")
