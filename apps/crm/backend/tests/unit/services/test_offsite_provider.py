"""Выбор провайдера внешней копии (OPS-YADISK): настроенный Google Drive остаётся без миграции."""

import pytest

from app.schemas.settings import IntegrationsSettings
from app.services.offsite_connector import provider_of


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({}, "yandex"),
        ({"offsite_gdrive": {"folder_id": "0AbCdEfGhIjKlMnOpQrStUvWxYz"}}, "gdrive"),
        (
            {
                "offsite_provider": "yandex",
                "offsite_gdrive": {"folder_id": "0AbCdEfGhIjKlMnOpQrStUvWxYz"},
            },
            "yandex",
        ),
        ({"offsite_provider": "gdrive"}, "gdrive"),
    ],
)
def test_provider_of_settings_saved_before_and_after_yandex(
    stored: dict[str, object], expected: str
) -> None:
    assert provider_of(IntegrationsSettings.model_validate(stored)) == expected
