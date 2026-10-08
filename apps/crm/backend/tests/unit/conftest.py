import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-тесты не зависят от переменных окружения машины/CI."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
