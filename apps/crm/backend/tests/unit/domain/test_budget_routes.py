"""Лимиты провайдеров и мягкий бюджет (ADR-0014, Q-008): куда пойдёт вызов модели."""

import pytest

from app.domain.budget import Route, choose_route, provider_over

LIMITS = {"anthropic": 3.0, "gemini": 1.0, "openai": 0.0}


@pytest.mark.parametrize(
    ("provider", "spent", "expected"),
    [
        ("anthropic", {"anthropic": 2.99}, False),
        ("anthropic", {"anthropic": 3.0}, True),
        ("anthropic", {"anthropic": 7.0}, True),
        ("gemini", {"anthropic": 7.0}, False),
        ("gemini", {"gemini": 1.0}, True),
        ("openai", {"openai": 100.0}, False),  # 0 — без лимита
        ("mistral", {"mistral": 100.0}, False),  # лимит не задан
        (None, {"anthropic": 100.0}, False),  # провайдер неизвестен
    ],
)
def test_provider_over(provider: str | None, spent: dict[str, float], expected: bool) -> None:
    assert provider_over(provider, spent, LIMITS) is expected


P, F, U = Route.PRIMARY, Route.FALLBACK, Route.UNAVAILABLE


@pytest.mark.parametrize(
    ("primary_over", "fallback_over", "soft_over", "allows_fallback", "enabled", "expected"),
    [
        # всё в норме
        (False, False, False, True, True, P),
        (False, False, False, False, True, P),
        # мягкий бюджет: диалог → резерв, квалификатор продолжает
        (False, False, True, True, True, F),
        (False, False, True, False, True, P),
        (False, False, True, True, False, P),  # переход на резерв выключен
        (False, True, True, True, True, P),  # резерв сам за лимитом — остаёмся
        # лимит провайдера: диалог → резерв, если тот в лимите, иначе честный отказ
        (True, False, False, True, True, F),
        (True, False, False, True, False, F),  # жёсткий лимит не зависит от флага мягкого
        (True, True, False, True, True, U),
        (True, False, False, False, True, U),  # квалификатор/прочие — отказ
        (True, True, True, False, True, U),
    ],
)
def test_choose_route(
    primary_over: bool,
    fallback_over: bool,
    soft_over: bool,
    allows_fallback: bool,
    enabled: bool,
    expected: Route,
) -> None:
    assert (
        choose_route(
            primary_over=primary_over,
            fallback_over=fallback_over,
            soft_over=soft_over,
            allows_fallback=allows_fallback,
            fallback_enabled=enabled,
        )
        is expected
    )
