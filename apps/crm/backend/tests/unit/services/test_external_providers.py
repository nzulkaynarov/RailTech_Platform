"""Строки вендоров не пропадают, когда шлюз недоступен (ADR-0024): значения по умолчанию алиасов."""

from pathlib import Path

from app.integrations.litellm_catalog import ModelEntry
from app.services.external_services.providers import providers

DEFAULTS = Path(__file__).resolve().parents[4] / "infra" / "litellm.models.yaml"


class Catalog:
    def __init__(self, entries: dict[str, ModelEntry]) -> None:
        self._entries = entries

    async def entries(self) -> dict[str, ModelEntry]:
        return self._entries


async def test_gateway_aliases_win() -> None:
    catalog = Catalog({"dialog-model": ModelEntry("dialog-model", "openai", "openai/x")})
    assert await providers(catalog, DEFAULTS) == {"dialog-model": "openai"}  # type: ignore[arg-type]


async def test_gateway_down_falls_back_to_defaults_file() -> None:
    found = await providers(Catalog({}), DEFAULTS)  # type: ignore[arg-type]
    assert found["dialog-model"] == "anthropic"
    assert found["fallback-model"] == "gemini"


async def test_no_defaults_file_is_empty_not_error(tmp_path: Path) -> None:
    assert await providers(Catalog({}), tmp_path / "missing.yaml") == {}  # type: ignore[arg-type]
    assert await providers(Catalog({}), None) == {}  # type: ignore[arg-type]
