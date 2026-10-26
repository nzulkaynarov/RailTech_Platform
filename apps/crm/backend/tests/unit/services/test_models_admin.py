"""Смена модели роли из CRM (ADR-0020): параметры, ключ только в LiteLLM, замена deployment.

LiteLLM — подставной HTTP (respx), реальные провайдеры не вызываются.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import AnyHttpUrl, SecretStr

from app.domain.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.litellm_admin import LiteLLMAdmin, env_keys, load_defaults
from app.schemas.settings import AppSettings
from app.security.principal import Principal
from app.services import models_admin
from app.services.models_admin import ModelChange, ModelsAdminService, build_params, validate

SEED = Path(__file__).resolve().parents[4] / "infra" / "litellm.models.yaml"
BASE = "http://litellm.invalid:4000"
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))
DEFAULTS = load_defaults(SEED)
FAKE_KEY = "sk-ant-fake-crm-key-4321"


def test_seed_file_defines_all_roles_with_env_keys() -> None:
    assert set(DEFAULTS) == {
        "dialog-model",
        "qualifier-model",
        "judge-model",
        "fallback-model",
        "embed-model",
    }
    assert env_keys(DEFAULTS) == {
        "anthropic": "os.environ/ANTHROPIC_API_KEY",
        "gemini": "os.environ/GEMINI_API_KEY",
    }


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (ModelChange("mistral", "x"), "provider"),
        (ModelChange("anthropic", "anthropic/claude-x"), "model"),
        (ModelChange("anthropic", "bad model id"), "model"),
        (ModelChange("anthropic", "claude-x", api_base="ftp://x"), "api_base"),
        (ModelChange("anthropic", "claude-x", api_key="short"), "api_key"),
    ],
)
def test_validate_rejects(change: ModelChange, field: str) -> None:
    with pytest.raises(ValidationFailedError) as exc:
        validate(change)
    assert exc.value.details["field"] == field


def test_build_params_same_model_keeps_flags_and_env_key() -> None:
    params, info, source = build_params(
        "dialog-model", ModelChange("anthropic", "claude-sonnet-5-5"), DEFAULTS
    )
    assert params["model"] == "anthropic/claude-sonnet-5-5"
    assert params["api_key"] == "os.environ/ANTHROPIC_API_KEY"
    assert params["timeout"] == 20
    assert params["reasoning_effort"] == "low"
    assert info["supports_adaptive_thinking"] is True
    assert source == "env"


def test_build_params_other_provider_with_crm_key() -> None:
    params, info, source = build_params(
        "dialog-model",
        ModelChange("openai", "gpt-x", api_key=FAKE_KEY, api_base="https://example.invalid/v1"),
        DEFAULTS,
    )
    assert params["model"] == "openai/gpt-x"
    assert params["api_key"] == FAKE_KEY
    assert params["api_base"] == "https://example.invalid/v1"
    assert info == {}  # флаги claude не переносятся на чужую модель
    assert source == "crm"


def test_build_params_requires_key_without_env_reference() -> None:
    with pytest.raises(ValidationFailedError) as exc:
        build_params("dialog-model", ModelChange("openai", "gpt-x"), DEFAULTS)
    assert exc.value.details["field"] == "api_key"


def _info(*items: tuple[str, str, str, bool]) -> dict[str, Any]:
    return {
        "data": [
            {
                "model_name": alias,
                "litellm_params": {"model": model},
                "model_info": {"id": mid, "db_model": in_db},
            }
            for mid, alias, model, in_db in items
        ]
    }


class _Recorder:
    def __init__(self) -> None:
        self.invalidated = 0
        self.audits: list[dict[str, Any]] = []


class _Settings:
    """Настройки в памяти: `SettingsService.get/update` без БД; запоминает записанное."""

    def __init__(self) -> None:
        self.current = AppSettings()
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def get(self) -> AppSettings:
        return self.current

    async def update(self, key: str, value: dict[str, Any], user_id: int | None) -> None:
        self.writes.append((key, value))
        self.current = self.current.model_copy(
            update={key: type(getattr(self.current, key)).model_validate(value)}
        )


def _service(
    rec: _Recorder, monkeypatch: pytest.MonkeyPatch, settings: _Settings | None = None
) -> ModelsAdminService:
    service = ModelsAdminService(
        sessions=None,  # type: ignore[arg-type]  # БД не нужна: re-auth и аудит подменены
        admin=LiteLLMAdmin(AnyHttpUrl(BASE), SecretStr("sk-master-test")),
        defaults=DEFAULTS,
        invalidate=lambda: setattr(rec, "invalidated", rec.invalidated + 1),
        new_id=lambda alias: f"rt-{alias}-new",
        settings_service=settings,  # type: ignore[arg-type]  # подставной: только get и update
    )

    async def no_reauth(_: int, __: str) -> None:
        return None

    async def record(*args: Any, **kwargs: Any) -> None:
        rec.audits.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(service, "_reauth", no_reauth)
    monkeypatch.setattr(service, "_audit", record)
    return service


@respx.mock
async def test_change_creates_new_then_deletes_old(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder()
    service = _service(rec, monkeypatch)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(
            200, json=_info(("rt-old", "dialog-model", "anthropic/claude-sonnet-5-5", True))
        )
    )
    new = respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={"model_id": "x"}))
    delete = respx.post(f"{BASE}/model/delete").mock(httpx.Response(200, json={}))

    out = await service.change(
        ADMIN, "dialog-model", ModelChange("openai", "gpt-x", api_key=FAKE_KEY), "pw"
    )

    sent = json.loads(new.calls.last.request.content)
    assert sent["model_name"] == "dialog-model"
    assert sent["model_info"]["id"] == "rt-dialog-model-new"
    assert sent["litellm_params"]["api_key"] == FAKE_KEY  # ключ уходит только в LiteLLM
    assert json.loads(delete.calls.last.request.content) == {"id": "rt-old"}
    assert new.calls.last.request.headers["authorization"] == "Bearer sk-master-test"
    assert rec.invalidated == 1
    assert out.quality_check_recommended is True
    assert out.reindex_required is False
    assert (out.provider, out.model, out.key_source) == ("openai", "gpt-x", "crm")


@respx.mock
async def test_embed_change_requires_reindex(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(200, json=_info(("rt-e", "embed-model", "gemini/gemini-embedding-2", True)))
    )
    respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={}))
    respx.post(f"{BASE}/model/delete").mock(httpx.Response(200, json={}))
    out = await service.change(
        ADMIN, "embed-model", ModelChange("openai", "text-embedding-x", api_key=FAKE_KEY), "pw"
    )
    assert out.reindex_required is True


@respx.mock
async def test_change_refuses_alias_still_in_config(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(
            200, json=_info(("cfg", "dialog-model", "anthropic/claude-sonnet-5-5", False))
        )
    )
    new = respx.post(f"{BASE}/model/new")
    with pytest.raises(ConflictError):
        await service.change(ADMIN, "dialog-model", ModelChange("anthropic", "claude-x"), "pw")
    assert not new.called


@respx.mock
async def test_litellm_error_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    respx.get(f"{BASE}/model/info").mock(httpx.Response(200, json=_info()))
    respx.post(f"{BASE}/model/new").mock(
        httpx.Response(400, json={"error": {"message": f"bad key {FAKE_KEY}"}})
    )
    with pytest.raises(UpstreamUnavailableError) as exc:
        await service.change(
            ADMIN, "dialog-model", ModelChange("openai", "gpt-x", api_key=FAKE_KEY), "pw"
        )
    assert FAKE_KEY not in str(exc.value.details)


async def test_unknown_alias_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    with pytest.raises(NotFoundError):
        await service.change(ADMIN, "nope", ModelChange("anthropic", "claude-x"), "pw")


@respx.mock
async def test_reset_restores_default(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(200, json=_info(("rt-x", "qualifier-model", "openai/gpt-x", True)))
    )
    new = respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={}))
    respx.post(f"{BASE}/model/delete").mock(httpx.Response(200, json={}))
    out = await service.reset(ADMIN, "qualifier-model", "pw")
    sent = json.loads(new.calls.last.request.content)
    assert sent["litellm_params"] == DEFAULTS["qualifier-model"].litellm_params
    assert sent["model_info"]["supports_adaptive_thinking"] is True
    assert out.key_source == "env"


@respx.mock
async def test_seed_creates_only_missing_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(_Recorder(), monkeypatch)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(
            200,
            json=_info(
                ("a", "dialog-model", "openai/gpt-x", True),
                ("b", "qualifier-model", "anthropic/claude-haiku-5-5", True),
                ("c", "judge-model", "anthropic/claude-sonnet-5-5", False),
            ),
        )
    )
    new = respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={}))
    created = await service.seed()
    assert created == ["fallback-model", "embed-model"]
    names = [json.loads(c.request.content)["model_name"] for c in new.calls]
    assert names == ["fallback-model", "embed-model"]


def test_providers_match_schema() -> None:
    from typing import get_args

    from app.schemas.spend import ModelChangeIn

    assert get_args(ModelChangeIn.model_fields["provider"].annotation) == models_admin.PROVIDERS


@respx.mock
async def test_change_remembers_key_mask_but_never_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Маска ключа (источник, последние 4 символа) для экрана «Модели ИИ»; сам ключ не хранится."""
    settings = _Settings()
    service = _service(_Recorder(), monkeypatch, settings)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(
            200, json=_info(("rt-old", "dialog-model", "anthropic/claude-sonnet-5-5", True))
        )
    )
    respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={}))
    respx.post(f"{BASE}/model/delete").mock(httpx.Response(200, json={}))

    await service.change(
        ADMIN, "dialog-model", ModelChange("openai", "gpt-x", api_key=FAKE_KEY), "pw"
    )

    mask = settings.current.integrations.model_keys["dialog-model"]
    assert (mask.source, mask.last4) == ("crm", FAKE_KEY[-4:])
    assert FAKE_KEY not in json.dumps(settings.writes, default=str)
    assert FAKE_KEY not in settings.current.model_dump_json()

    await service.change(ADMIN, "dialog-model", ModelChange("anthropic", "claude-x"), "pw")
    env_mask = settings.current.integrations.model_keys["dialog-model"]
    assert (env_mask.source, env_mask.last4) == ("env", None)


@respx.mock
async def test_reset_marks_key_as_from_server_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _Settings()
    service = _service(_Recorder(), monkeypatch, settings)
    respx.get(f"{BASE}/model/info").mock(
        httpx.Response(200, json=_info(("rt-x", "qualifier-model", "openai/gpt-x", True)))
    )
    respx.post(f"{BASE}/model/new").mock(httpx.Response(200, json={}))
    respx.post(f"{BASE}/model/delete").mock(httpx.Response(200, json={}))

    await service.reset(ADMIN, "qualifier-model", "pw")

    mask = settings.current.integrations.model_keys["qualifier-model"]
    assert (mask.source, mask.last4) == ("env", None)
