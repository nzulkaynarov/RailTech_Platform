"""Виртуальный ключ ERP в LiteLLM и состояние ИИ для консоли админа — без сети."""

from io import StringIO

import pytest
from ai.services.provision import AdminResponse, KeySpec, LangfuseTarget, allowed_models, key_settings, sync_erp_key
from django.core.management import call_command


class FakeAdmin:
    def __init__(self, *, exists: bool, fail: bool = False):
        self.exists = exists
        self.fail = fail
        self.requests: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, master_key, body=None):
        self.requests.append((method, url, body))
        if method == "GET":
            # Проверка существования — самим ключом ERP и без ключа в адресе.
            assert (url.endswith("/key/info"), master_key) == (True, SPEC.key)
        else:
            assert master_key == "sk-master"
        if method == "GET":
            return AdminResponse(200, {"info": {"key_alias": "erp"}}) if self.exists else AdminResponse(404, {})
        if self.fail:
            return AdminResponse(400, {"error": {"message": "nope"}})
        return AdminResponse(200, {"key": body["key"]})


SPEC = KeySpec(
    key="sk-erp-1",
    max_budget_usd=1.0,
    langfuse=LangfuseTarget(public_key="pk-lf-1", secret_key="sk-lf-1", host="http://langfuse-web:3000"),
)


def test_key_settings_carry_budget_langfuse_and_only_erp_models():
    body = key_settings(SPEC)
    assert body["key_alias"] == "erp"
    assert (body["max_budget"], body["budget_duration"]) == (1.0, "1d")
    assert body["models"] == allowed_models()
    assert set(body["models"]) == {"intake-model", "match-model", "draft-model", "enrich-model", "fallback-model"}
    logging = body["metadata"]["logging"][0]
    assert (logging["callback_name"], logging["callback_type"]) == ("langfuse", "success_and_failure")
    assert logging["callback_vars"]["langfuse_host"] == "http://langfuse-web:3000"


def test_no_budget_and_no_langfuse():
    body = key_settings(KeySpec(key="sk-erp-1", max_budget_usd=None))
    assert body["max_budget"] is None and body["budget_duration"] is None
    assert "logging" not in body["metadata"]


@pytest.mark.parametrize(
    "exists, path, outcome", [(False, "/key/generate", "created"), (True, "/key/update", "updated")]
)
def test_sync_is_idempotent(monkeypatch, exists, path, outcome):
    admin = FakeAdmin(exists=exists)
    monkeypatch.setattr("ai.services.provision._admin_request", admin)

    assert sync_erp_key("http://litellm:4000/", "sk-master", SPEC) == outcome

    method, url, body = admin.requests[-1]
    assert (method, url) == ("POST", f"http://litellm:4000{path}")
    assert body["key"] == "sk-erp-1"


def test_sync_reports_gateway_refusal(monkeypatch):
    monkeypatch.setattr("ai.services.provision._admin_request", FakeAdmin(exists=False, fail=True))
    with pytest.raises(RuntimeError, match="/key/generate"):
        sync_erp_key("http://litellm:4000", "sk-master", SPEC)


def _sync_output(monkeypatch, settings, *, erp_key, master="sk-master"):
    settings.LITELLM_BASE_URL = "http://litellm:4000"
    settings.LITELLM_API_KEY = erp_key
    monkeypatch.setenv("LITELLM_MASTER_KEY", master)
    out = StringIO()
    call_command("ai_gateway_sync", stdout=out)
    return out.getvalue()


def test_command_skips_master_key_mode(monkeypatch, settings):
    monkeypatch.setattr("ai.services.provision._admin_request", lambda *a, **k: pytest.fail("no admin call"))
    assert "мастер-ключом" in _sync_output(monkeypatch, settings, erp_key="sk-master")


def test_command_never_fails_on_gateway_errors(monkeypatch, settings):
    monkeypatch.setattr("ai.services.provision._admin_request", FakeAdmin(exists=False, fail=True))
    assert "не принял" in _sync_output(monkeypatch, settings, erp_key="sk-erp-1")


def test_command_registers_key_with_langfuse_from_env(monkeypatch, settings):
    admin = FakeAdmin(exists=False)
    monkeypatch.setattr("ai.services.provision._admin_request", admin)
    monkeypatch.setenv("ERP_LANGFUSE_PUBLIC_KEY", "pk-lf-9")
    monkeypatch.setenv("ERP_LANGFUSE_SECRET_KEY", "sk-lf-9")
    settings.AI_DAILY_BUDGET_USD = 2

    output = _sync_output(monkeypatch, settings, erp_key="sk-erp-1")

    assert "created" in output
    body = admin.requests[-1][2]
    assert body["max_budget"] == 2.0
    assert body["metadata"]["logging"][0]["callback_vars"]["langfuse_public_key"] == "pk-lf-9"


@pytest.mark.django_db
def test_status_without_gateway_makes_no_network_call(settings):
    from ai.services.status import ai_status

    settings.LITELLM_BASE_URL = ""
    settings.LITELLM_API_KEY = ""
    settings.AI_IMPORT_ENABLED = False

    status = ai_status()

    assert status["system"] == "erp" and status["enabled"] is False
    assert status["gateway"] == {"configured": False, "reachable": None, "key": None}
    assert status["today"]["calls"] == 0 and status["today"]["budget_usd"] == "1.0"
    assert set(status["prompts"]) >= {"intake", "match", "diff", "enrich"}


@pytest.mark.django_db
def test_status_reads_gateway_liveness_and_key_budget(settings, monkeypatch):
    import httpx
    from ai.services import status as status_module

    settings.LITELLM_BASE_URL = "http://litellm:4000"
    settings.LITELLM_API_KEY = "sk-erp-1"
    calls = []

    def _fake_get(url, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/key/info"):
            payload = {"info": {"key_alias": "erp", "spend": 0.12, "max_budget": 1.0, "budget_duration": "1d"}}
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(status_module.httpx, "get", _fake_get)

    gateway = status_module.gateway_status()

    assert gateway["reachable"] is True
    assert gateway["key"]["max_budget_usd"] == 1.0 and gateway["key"]["spend_usd"] == 0.12
    assert calls == ["http://litellm:4000/health/liveliness", "http://litellm:4000/key/info"]
