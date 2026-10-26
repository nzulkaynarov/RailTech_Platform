"""`SettingsService.merge_map` (W13-A1): маска ключа модели не откатывает чужие поля настроек.

Кэш настроек процесса живёт 30 с; запись целого ключа из кэша затёрла бы поля, изменённые
другим запросом (адрес ERP, срок приёма прежнего секрета). `merge_map` читает строку под
`FOR UPDATE` мимо кэша и пишет только свою запись.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.settings import SettingsService

pytestmark = pytest.mark.integration

MASK = {
    "source": "crm",
    "last4": "4321",
    "updated_at": datetime(2026, 10, 26, tzinfo=UTC).isoformat(),
}


async def test_erp_fields_changed_after_cache_fill_survive_a_mask_write(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    cached = SettingsService(sessions)
    await cached.get()  # кэш заполнен: адреса ERP ещё нет

    # другой процесс (или соседний запрос) сохраняет адрес ERP и срок приёма прежнего секрета
    other = SettingsService(sessions)
    await other.update(
        "integrations",
        {
            "erp_base_url": "http://erp.test",
            "erp_previous_secret_until": "2026-10-27T00:00:00+00:00",
        },
        None,
    )
    assert (await cached.get()).integrations.erp_base_url == ""  # кэш устарел, как в жизни

    await cached.merge_map("integrations", "model_keys", {"dialog-model": MASK}, None)

    fresh = (await SettingsService(sessions).get()).integrations
    assert fresh.erp_base_url == "http://erp.test"
    assert fresh.erp_previous_secret_until is not None
    assert fresh.model_keys["dialog-model"].last4 == "4321"
    # и кэш процесса после записи свежий
    assert (await cached.get()).integrations.erp_base_url == "http://erp.test"


async def test_second_mask_keeps_the_first_and_works_without_a_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    service = SettingsService(sessions)
    await service.merge_map("integrations", "model_keys", {"dialog-model": MASK}, None)
    await service.merge_map(
        "integrations",
        "model_keys",
        {"embed-model": {**MASK, "source": "env", "last4": None}},
        None,
    )

    masks = (await SettingsService(sessions).get()).integrations.model_keys
    assert set(masks) == {"dialog-model", "embed-model"}
    assert masks["embed-model"].source == "env"
