from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.language import Language
from app.schemas.settings import AppSettings, BusinessHoursSettings, KbSettings
from app.services.settings import SettingsService, _merge, _with_env_defaults


def test_defaults_without_rows() -> None:
    assert _merge({}) == AppSettings()


def test_row_overrides_key() -> None:
    merged = _merge({"kb": {"min_score": 0.7, "top_k": 4}})
    assert merged.kb == KbSettings(min_score=0.7, top_k=4)
    assert merged.bot == AppSettings().bot


def test_invalid_row_falls_back_to_default() -> None:
    merged = _merge({"kb": {"min_score": 5}})
    assert merged.kb == KbSettings()


def test_localized_text_formatting() -> None:
    texts = AppSettings().texts
    assert "RailTech" in texts.help.get("en", company="RailTech")
    assert texts.consent_button.get("uz") == "Roziman"


def test_all_texts_have_three_languages() -> None:
    texts = AppSettings().texts
    for name, value in texts:
        if name == "consent_version":
            continue
        assert all([value.ru, value.uz, value.en]), name


@pytest.mark.parametrize(
    ("weekdays", "language", "expected"),
    [
        ([0, 1, 2, 3, 4], "ru", "пн–пт с 9:00 до 18:00 по Ташкенту"),
        ([0, 2, 4], "ru", "пн, ср, пт с 9:00 до 18:00 по Ташкенту"),
        ([0, 1, 2, 3, 4, 5], "en", "Mon–Sat, 9:00–18:00 Tashkent time"),
        ([0, 1, 2, 3, 4], "uz", "dushanba–juma, Toshkent vaqti bilan 9:00 dan 18:00 gacha"),
    ],
)
def test_off_hours_text_follows_business_hours(
    weekdays: list[int], language: Language, expected: str
) -> None:
    """Аудит BOT-19: часы работы в тексте лиду берутся из настроек, а не зашиты."""
    cfg = AppSettings(business_hours=BusinessHoursSettings(weekdays=weekdays))
    assert cfg.business_hours.describe(language) == expected
    # Переопределённый админом текст с {hours} по-прежнему получает расписание из настроек.
    custom = cfg.texts.model_copy(
        update={"off_hours": cfg.texts.off_hours.model_copy(update={language: "{hours}"})}
    )
    assert cfg.model_copy(update={"texts": custom}).lead_notice("off_hours", language) == expected


# --- W15-H8a: адрес CRM по умолчанию — из окружения, заданное админом не трогаем ---------------

ENV_CRM = "https://crm.example.com"


def test_env_default_replaces_factory_localhost() -> None:
    cfg = _with_env_defaults(_merge({}), ENV_CRM)
    assert cfg.company.crm_base_url == ENV_CRM
    assert cfg.company.name == "RailTech"  # остальные поля компании не затронуты


def test_env_default_replaces_stored_factory_value() -> None:
    """В БД осталось значение по умолчанию (`http://localhost`) — это не выбор админа."""
    cfg = _with_env_defaults(_merge({"company": {"crm_base_url": "http://localhost/"}}), ENV_CRM)
    assert cfg.company.crm_base_url == ENV_CRM


@pytest.mark.parametrize("chosen", ["https://crm.owner.example", "http://localhost:5173"])
def test_env_default_never_overrides_admin_value(chosen: str) -> None:
    cfg = _with_env_defaults(_merge({"company": {"crm_base_url": chosen}}), ENV_CRM)
    assert cfg.company.crm_base_url == chosen


@pytest.mark.parametrize("env", [None, ""])
def test_without_env_nothing_changes(env: str | None) -> None:
    assert _with_env_defaults(_merge({}), env) == AppSettings()


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def scalars(self, _stmt: object) -> _Rows:
        return _Rows(self._rows)

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


async def test_service_get_applies_env_default_and_keeps_admin_value() -> None:
    fresh = SettingsService(lambda: _Session([]), crm_base_url_default=ENV_CRM)  # type: ignore[arg-type]
    assert (await fresh.get()).company.crm_base_url == ENV_CRM
    # Форма «Настройки» видит сохранённое (заводское) значение, а не выведенное из окружения.
    assert (await fresh.raw())["company"]["crm_base_url"] == "http://localhost"

    row = SimpleNamespace(key="company", value={"crm_base_url": "https://crm.owner.example"})
    chosen = SettingsService(lambda: _Session([row]), crm_base_url_default=ENV_CRM)  # type: ignore[arg-type]
    assert (await chosen.get()).company.crm_base_url == "https://crm.owner.example"


async def test_saving_company_form_does_not_persist_derived_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Форма «Компания» читает raw() и сохраняет другое поле: выведенный адрес в БД не попадает."""
    written: list[dict[str, Any]] = []

    async def upsert(_session: Any, _key: str, payload: dict[str, Any], _user: Any) -> None:
        written.append(payload)

    monkeypatch.setattr(SettingsService, "_upsert", staticmethod(upsert))
    service = SettingsService(lambda: _Session([]), crm_base_url_default=ENV_CRM)  # type: ignore[arg-type]
    form = (await service.raw())["company"]
    await service.update("company", {**form, "phone": "+998 71 000 00 00"}, user_id=1)
    (payload,) = written
    assert payload["phone"] == "+998 71 000 00 00"
    assert ENV_CRM not in payload["crm_base_url"]
    assert payload["crm_base_url"] == "http://localhost"
    # Потребители по-прежнему получают адрес из окружения.
    assert (await service.get()).company.crm_base_url == ENV_CRM
