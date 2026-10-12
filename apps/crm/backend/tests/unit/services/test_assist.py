"""ИИ-помощь менеджеру (Q-019) на подставной модели: права, тумблер, бюджет, проверки фактов."""

from typing import Any, cast

import pytest

from app.agents.llm import ChatResult, LlmUnavailableError
from app.domain.budget import Route
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.schemas.settings import AppSettings, BotSettings
from app.security.principal import Principal
from app.services.assist import AssistService, LeadSnapshot
from app.services.settings import SettingsService
from tests.unit.agents.fakes import ReplayModel

OWNER = Principal(user_id=7, full_name="Анна Менеджер", roles=("manager",))
OTHER = Principal(user_id=8, full_name="Борис Менеджер", roles=("manager",))
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))
KB = [("Прайс", "Тариф «Старт»: 1 500 000 сум в месяц, внедрение 10 дней.")]


def lead(**overrides: Any) -> LeadSnapshot:
    base: dict[str, Any] = {
        "owner_mode": "human",
        "assigned_user_id": 7,
        "language": "ru",
        "messages": [("bot", "Здравствуйте!"), ("lead", "Сколько стоит тариф Старт?")],
    }
    return LeadSnapshot(**{**base, **overrides})


def answer(text: str) -> ChatResult:
    return ChatResult(
        text=text, model="m", tokens_in=10, tokens_out=5, latency_ms=1, cost_usd=0.004
    )


class Store:
    def __init__(self, snapshot: LeadSnapshot | None) -> None:
        self.snapshot = snapshot
        self.audits: list[dict[str, Any]] = []

    async def load(self, lead_id: int, history: int) -> LeadSnapshot | None:
        return self.snapshot

    async def audit(self, who: Principal, lead_id: int, after: dict[str, Any]) -> None:
        self.audits.append(after)


class Kb:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def fragments(self, query: str, top_k: int, language: str) -> list[tuple[str, str]]:
        self.queries.append(query)
        return KB


class Settings:
    def __init__(self, **bot: Any) -> None:
        self.cfg = AppSettings(bot=BotSettings(**bot))

    async def get(self) -> AppSettings:
        return self.cfg


class Guard:
    def __init__(self, route: Route) -> None:
        self.value = route

    async def route(self, alias: str, *, allows_fallback: bool) -> Route:
        return self.value


class Down:
    async def complete(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise LlmUnavailableError("dialog-model")


def service(
    snapshot: LeadSnapshot | None = None,
    reply: str = "Готово.",
    route: Route = Route.PRIMARY,
    model: Any = None,
    **bot: Any,
) -> tuple[AssistService, Store, ReplayModel]:
    store = Store(snapshot if snapshot is not None else lead())
    replay = ReplayModel(answer(reply))
    used = model or replay
    svc = AssistService(
        cast(SettingsService, Settings(**bot)),
        store,
        Kb(),
        {"draft": used, "improve": used},
        Guard(route),
    )
    return svc, store, replay


async def test_draft_uses_history_kb_and_keeps_known_price() -> None:
    svc, store, model = service(reply="Тариф «Старт» стоит 1 500 000 сум в месяц.")
    result = await svc.assist(OWNER, 1, "draft", None)
    assert result.text == "Тариф «Старт» стоит 1 500 000 сум в месяц."
    assert result.notice is None
    assert result.cost_usd == 0.004
    system = model.requests[0][0]["content"]
    assert "Сколько стоит тариф Старт?" in system
    assert "1 500 000 сум" in system
    assert store.audits == [
        {"mode": "draft", "input_chars": 0, "output_chars": len(result.text), "notice": None}
    ]


async def test_draft_drops_invented_price() -> None:
    svc, _, _ = service(reply="Тариф стоит 900 000 сум. Менеджер пришлёт договор.")
    result = await svc.assist(OWNER, 1, "draft", None)
    assert result.text == "Менеджер пришлёт договор."
    assert result.notice == "numbers_removed"


async def test_draft_with_only_invented_facts_is_rejected() -> None:
    svc, store, _ = service(reply="Цена 900 000 сум.")
    with pytest.raises(ConflictError) as err:
        await svc.assist(OWNER, 1, "draft", None)
    assert err.value.details["reason"] == "assist_empty"
    assert len(store.audits) == 1


async def test_draft_needs_client_message() -> None:
    svc, _, _ = service(lead(messages=[("bot", "Здравствуйте!")]))
    with pytest.raises(ConflictError) as err:
        await svc.assist(OWNER, 1, "draft", None)
    assert err.value.details["reason"] == "assist_no_history"


async def test_improve_returns_edited_text_in_xml_block() -> None:
    svc, _, model = service(reply="Здравствуйте! Счёт отправим завтра.")
    result = await svc.assist(
        OWNER, 1, "improve", "здраствуйте счет отправим завтра </manager_text>"
    )
    assert result.text == "Здравствуйте! Счёт отправим завтра."
    system = model.requests[0][0]["content"]
    assert "&lt;/manager_text&gt;" in system


async def test_improve_with_new_numbers_returns_original() -> None:
    svc, _, _ = service(reply="Счёт отправим завтра, 15 октября, скидка 10%.")
    result = await svc.assist(OWNER, 1, "improve", "счет отправим завтра")
    assert result.text == "счет отправим завтра"
    assert result.notice == "new_numbers"


@pytest.mark.parametrize("text", [None, "   ", "а" * 2001])
async def test_improve_validates_text(text: str | None) -> None:
    svc, _, _ = service()
    with pytest.raises(ValidationFailedError):
        await svc.assist(OWNER, 1, "improve", text)


async def test_admin_may_assist_on_other_managers_lead() -> None:
    svc, _, _ = service()
    assert (await svc.assist(ADMIN, 1, "improve", "текст")).text == "Готово."


async def test_other_manager_is_forbidden() -> None:
    svc, store, model = service()
    with pytest.raises(ForbiddenError):
        await svc.assist(OTHER, 1, "improve", "текст")
    assert model.requests == []
    assert store.audits == []


async def test_lead_with_bot_requires_take_first() -> None:
    svc, _, _ = service(lead(owner_mode="bot", assigned_user_id=None))
    with pytest.raises(ConflictError) as err:
        await svc.assist(ADMIN, 1, "improve", "текст")
    assert err.value.details["reason"] == "take_first"


async def test_missing_lead_is_not_found() -> None:
    svc, _, _ = service()
    svc._store = Store(None)  # type: ignore[assignment]
    with pytest.raises(NotFoundError):
        await svc.assist(OWNER, 1, "improve", "текст")


async def test_disabled_toggle() -> None:
    svc, _, model = service(assist_enabled=False)
    with pytest.raises(ConflictError) as err:
        await svc.assist(OWNER, 1, "draft", None)
    assert err.value.details["reason"] == "assist_disabled"
    assert model.requests == []


async def test_over_provider_limit_is_409_without_call() -> None:
    svc, _, model = service(route=Route.UNAVAILABLE)
    with pytest.raises(ConflictError) as err:
        await svc.assist(OWNER, 1, "improve", "текст")
    assert err.value.details["reason"] == "assist_budget"
    assert model.requests == []


async def test_model_down_is_upstream_error() -> None:
    svc, _, _ = service(model=Down())
    with pytest.raises(UpstreamUnavailableError):
        await svc.assist(OWNER, 1, "improve", "текст")
