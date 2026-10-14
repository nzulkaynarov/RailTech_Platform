"""Промпты — файлы с версией по хэшу; ни одного SDK провайдера в коде ERP (DoD M1-ERP-06)."""

import re
from pathlib import Path

import pytest
from ai.services.prompts import PromptError, available_prompts, load_prompt, prompt_version
from django.conf import settings

EXPECTED_PROMPTS = {
    "canonicalize",
    "compose",
    "diff",
    "enrich",
    "extract",
    "hs_lookup",
    "intake",
    "match",
    "preflight",
    "price_list",
}
PLACEHOLDERS = {
    "intake": {"unit_codes"},
    "price_list": {"max_rows"},
    "diff": {"issue_substituted", "issue_note_ignored"},
}
# Пакеты провайдеров моделей: импорт любого из них в ERP запрещён (ORCHESTRATOR §3.6).
PROVIDER_SDK = re.compile(
    r"^\s*(?:import|from)\s+(anthropic|openai|google\.generativeai|google\.genai|mistralai|cohere|litellm)\b",
    re.MULTILINE,
)


def test_every_ai_feature_has_its_prompt_file():
    assert set(available_prompts()) == EXPECTED_PROMPTS


@pytest.mark.parametrize("name", sorted(EXPECTED_PROMPTS))
def test_prompt_renders_with_exactly_its_placeholders(name):
    prompt = load_prompt(name)
    assert prompt.placeholders == PLACEHOLDERS.get(name, set())
    values = {key: "VALUE" for key in prompt.placeholders}
    text = prompt.render(**values)
    assert "{{" not in text and text.strip()


def test_version_is_the_content_hash():
    prompt = load_prompt("match")
    assert prompt.version == prompt_version(prompt.template)
    assert len(prompt.version) == 12
    assert prompt_version(prompt.template + " ") != prompt.version


def test_missing_or_extra_values_are_a_code_error():
    with pytest.raises(PromptError):
        load_prompt("intake").render()
    with pytest.raises(PromptError):
        load_prompt("match").render(extra="x")
    with pytest.raises(PromptError):
        load_prompt("no_such_prompt")
    with pytest.raises(PromptError):
        load_prompt("../settings")


def test_prompts_are_industry_neutral():
    """Промпты без отраслевых примеров (M1-ERP-04): товары и услуги любого бизнеса."""
    banned = re.compile(r"вагон|рельс|тормозн|автосцеп|локомотив|железнодорож", re.IGNORECASE)
    for name in EXPECTED_PROMPTS:
        assert not banned.search(load_prompt(name).template), name


def test_no_provider_sdk_imports_anywhere_in_erp_backend():
    backend = Path(settings.BASE_DIR)
    offenders = [
        str(path.relative_to(backend))
        for path in backend.rglob("*.py")
        if "migrations" not in path.parts and PROVIDER_SDK.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_requirements_have_no_provider_sdk():
    backend = Path(settings.BASE_DIR)
    for name in ("requirements.in", "requirements.txt", "requirements-dev.txt"):
        text = (backend / name).read_text(encoding="utf-8").lower()
        assert not re.search(r"^(anthropic|openai|litellm)[=<>~ ]", text, re.MULTILINE), name
