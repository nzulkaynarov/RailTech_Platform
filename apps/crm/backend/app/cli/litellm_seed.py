"""`python -m app litellm-seed` — модели ролей по умолчанию в БД LiteLLM (ADR-0020).

Идемпотентно: создаёт только алиасы, которых в прокси нет; изменённые из CRM не трогает.
Запускается сервисом `litellm-seed` в compose перед api/worker.
"""

import argparse

from app.container import get_container
from app.integrations.litellm_admin import LiteLLMAdmin, load_defaults
from app.services.models_admin import ModelsAdminService


async def run(_: argparse.Namespace) -> int:
    c = get_container()
    s = c.settings
    service = ModelsAdminService(
        c.session_factory,
        LiteLLMAdmin(s.litellm_base_url, s.litellm_api_key),
        load_defaults(s.litellm_models_path),
        c.model_catalog.invalidate,
    )
    try:
        created = await service.seed()
    finally:
        await c.aclose()
    message = "созданы алиасы " + ", ".join(created) if created else "все алиасы на месте"
    print(f"LiteLLM: {message}")  # noqa: T201
    return 0
