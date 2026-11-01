"""D17G-3: адрес кабинета — откуда берётся, сохранение своего поля, проверка `GET /health`."""

from typing import Any

import httpx
import pytest

from app.services.cabinet_url import CabinetUrlService


class _Settings:
    """Хранилище настроек в памяти: `raw()` и `update()` как у `SettingsService`."""

    def __init__(self, company: dict[str, Any] | None = None) -> None:
        self.company = {"name": "Рельс", "phone": "+998", "cabinet_url": "", **(company or {})}
        self.saved: list[dict[str, Any]] = []

    async def raw(self) -> dict[str, dict[str, Any]]:
        return {"company": dict(self.company)}

    async def update(
        self, key: str, value: dict[str, Any], user_id: Any, actor: Any = None
    ) -> None:
        from app.schemas.settings import CompanySettings

        assert key == "company"
        validated = CompanySettings.model_validate(value).model_dump(mode="json")
        self.company = validated
        self.saved.append(validated)


def _service(settings: _Settings, env: str | None = None, handler: Any = None) -> CabinetUrlService:
    transport = httpx.MockTransport(handler) if handler else None
    return CabinetUrlService(settings, env, transport)  # type: ignore[arg-type]


async def test_address_saved_beats_env_and_env_beats_nothing() -> None:
    assert (await _service(_Settings()).address()).source == "none"
    env = await _service(_Settings(), "https://cabinet.env.example").address()
    assert (env.url, env.source) == ("https://cabinet.env.example", "env")
    saved = await _service(
        _Settings({"cabinet_url": "https://lk.example"}), "https://cabinet.env.example"
    ).address()
    assert (saved.url, saved.source, saved.env_url) == (
        "https://lk.example",
        "saved",
        "https://cabinet.env.example",
    )


async def test_save_changes_only_the_cabinet_address() -> None:
    settings = _Settings()
    address = await _service(settings).save(" https://lk.example/ ", 1, None)
    assert address.url == "https://lk.example"
    assert address.source == "saved"
    assert settings.company["name"] == "Рельс"
    assert settings.company["phone"] == "+998"


async def test_save_refuses_a_non_http_address() -> None:
    settings = _Settings()
    with pytest.raises(ValueError, match="нужен адрес вида"):
        await _service(settings).save("cabinet.example.com", 1, None)
    assert settings.saved == []


async def test_check_ok_when_the_cabinet_answers_healthy() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="healthy\n")

    found = await _service(
        _Settings({"cabinet_url": "https://lk.example"}), handler=handler
    ).check()
    assert (found.result, found.url, found.status_code) == ("ok", "https://lk.example", 200)
    assert seen == ["https://lk.example/health"]


@pytest.mark.parametrize(
    ("response", "result", "code"),
    [
        (httpx.Response(404, text="not found"), "bad_status", 404),
        (httpx.Response(200, text="<!doctype html>"), "not_cabinet", 200),
    ],
)
async def test_check_says_what_is_wrong(response: httpx.Response, result: str, code: int) -> None:
    found = await _service(_Settings(), handler=lambda _r: response).check("https://lk.example")
    assert (found.result, found.status_code) == (result, code)


async def test_check_unreachable_and_not_set() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (await _service(_Settings(), handler=down).check("https://lk.example")).result == (
        "unreachable"
    )
    assert (await _service(_Settings()).check()).result == "not_set"
    assert (await _service(_Settings()).check("javascript:alert(1)")).result == "unreachable"
