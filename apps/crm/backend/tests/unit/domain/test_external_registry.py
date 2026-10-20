"""Реестр внешних сервисов и правила выключателя вендора (M3-CRM-12, ADR-0024)."""

import pytest

from app.domain import external_registry as reg

# Алиасы по умолчанию (`infra/ai/litellm.models.yaml`): Claude — роли CRM и ERP,
# Gemini — запасная модель и поиск.
DEFAULT: dict[str, str | None] = {
    "dialog-model": "anthropic",
    "qualifier-model": "anthropic",
    "judge-model": "anthropic",
    "fallback-model": "gemini",
    "embed-model": "gemini",
    "intake-model": "anthropic",
    "match-model": "anthropic",
    "draft-model": "anthropic",
    "enrich-model": "anthropic",
}


def keys(providers: dict[str, str | None]) -> list[str]:
    return [s.key for s in reg.registry(providers)]


def test_registry_lists_every_external_service_of_the_ensemble() -> None:
    assert keys(DEFAULT) == [
        "telegram",
        "litellm",
        "vendor.anthropic",
        "vendor.gemini",
        "langfuse",
        "mail",
        "s3",
        "docling",
        "erp_sync",
        "erp_handoff",
        "erp_events",
        "backup",
        "tls.crm",
        "tls.erp",
        "tls.cabinet",
        "erp.cbu_rates",
        "erp.customs_tariff",
        "erp.mail",
        "erp.sentry",
    ]


def test_every_entry_has_human_text_and_a_known_check_plan() -> None:
    for spec in reg.registry(DEFAULT):
        assert spec.title, spec.key
        assert spec.purpose, spec.key
        assert spec.check, spec.key
        assert set(spec.tiers) <= {"cheap", "heavy"}
        if spec.source == "crm":
            assert spec.tiers, f"{spec.key}: CRM-сервис без проверки"
        else:
            assert spec.tiers == (), spec.key
            assert spec.system == "erp", spec.key
        assert spec.fix_path is None or spec.fix_path.startswith("/"), spec.key


def test_keys_are_unique_and_url_safe() -> None:
    found = keys(DEFAULT)
    assert len(found) == len(set(found))
    assert all(k.replace(".", "").replace("_", "").isalnum() and k == k.lower() for k in found)


def test_vendors_come_from_aliases_one_per_provider() -> None:
    providers = {**DEFAULT, "qualifier-model": "openai", "unknown-model": None}
    vendors = [s for s in reg.registry(providers) if s.vendor]
    assert [v.vendor for v in vendors] == ["anthropic", "openai", "gemini"]
    anthropic = vendors[0]
    assert anthropic.title == "Модели ИИ: Anthropic (Claude)"
    assert anthropic.purpose.startswith("Роли: Диалог, Проверка качества, ERP: разбор запроса")
    assert anthropic.switch == "vendor"
    assert anthropic.fix_path == "/models"


def test_without_gateway_aliases_registry_still_has_the_rest() -> None:
    assert "vendor.anthropic" not in keys({})
    assert {"telegram", "litellm", "mail", "erp.sentry"} <= set(keys({}))


def test_erp_entries_wait_for_m3_erp_06() -> None:
    erp = [s for s in reg.registry(DEFAULT) if s.source == "erp"]
    assert {s.key for s in erp} == {
        "erp.cbu_rates",
        "erp.customs_tariff",
        "erp.mail",
        "erp.sentry",
    }
    assert all(s.switch is None for s in erp)


@pytest.mark.parametrize(
    ("key", "switch"),
    [
        ("telegram", "telegram"),
        ("langfuse", "langfuse"),
        ("mail", "mail"),
        ("vendor.anthropic", "vendor"),
        ("litellm", None),
        ("s3", None),
        ("docling", None),
        ("backup", None),
        ("tls.crm", None),
        ("erp.cbu_rates", None),
    ],
)
def test_switch_only_where_meaningful(key: str, switch: str | None) -> None:
    spec = reg.find(reg.registry(DEFAULT), key)
    assert spec is not None
    assert spec.switch == switch


def test_vendor_key_round_trip() -> None:
    assert reg.vendor_key("gemini") == "vendor.gemini"
    assert reg.vendor_of("vendor.gemini") == "gemini"
    assert reg.vendor_of("mail") is None


@pytest.mark.parametrize(
    ("vendor", "providers", "problem"),
    [
        ("anthropic", DEFAULT, None),
        ("gemini", DEFAULT, "запасную модель"),
        ("openai", DEFAULT, "не обслуживает"),
        ("anthropic", {k: v for k, v in DEFAULT.items() if k != "fallback-model"}, "не настроена"),
    ],
)
def test_switch_problem(vendor: str, providers: dict[str, str | None], problem: str | None) -> None:
    found = reg.switch_problem(vendor, providers)
    if problem is None:
        assert found is None
    else:
        assert found is not None
        assert problem in found


def test_redirects_move_chat_aliases_of_disabled_vendors_to_fallback() -> None:
    assert reg.redirects(["anthropic"], DEFAULT) == {
        "dialog-model": "fallback-model",
        "draft-model": "fallback-model",
        "enrich-model": "fallback-model",
        "intake-model": "fallback-model",
        "judge-model": "fallback-model",
        "match-model": "fallback-model",
        "qualifier-model": "fallback-model",
    }
    assert reg.redirects([], DEFAULT) == {}


def test_fallback_and_embeddings_are_never_redirected() -> None:
    providers = {"dialog-model": "openai", "embed-model": "openai", "fallback-model": "gemini"}
    assert reg.redirects(["openai", "gemini"], providers) == {"dialog-model": "fallback-model"}
    assert reg.blocked_aliases(["openai"], providers) == {"embed-model"}
    assert reg.blocked_aliases(["anthropic"], providers) == set()


def test_switch_effect_names_roles_in_words() -> None:
    effect = reg.switch_effect("anthropic", DEFAULT)
    assert effect.startswith("на запасную модель перейдут: Диалог, ERP: черновик КП")
    providers = {"dialog-model": "openai", "embed-model": "openai", "fallback-model": "gemini"}
    assert reg.switch_effect("openai", providers) == (
        "на запасную модель перейдут: Диалог; остановится: Поиск по базе знаний"
    )
