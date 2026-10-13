"""Коннектор «ERP» — точка расширения (ADR-0022, ADR-0018).

Здесь только ответ на вопрос «настроен ли коннектор»: адрес интеграционного API ERP и сервисный
токен (из хранилища секретов в БД, иначе из `.env`). Сам клиент ERP (handoff, зеркало сделок,
приёмник вебхуков) — задачи M3-CRM-02…04; до них коннектор всегда «не настроен», и жизненный
цикл работает в режиме `local` (`domain/backoffice.py`).
"""

from dataclasses import dataclass

import structlog

from app.config import Settings
from app.security.secrets_store import ERP_SERVICE_TOKEN, SecretsStore

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ErpConnection:
    base_url: str
    token: str


async def resolve_connection(store: SecretsStore, config: Settings) -> ErpConnection | None:
    """Адрес и токен ERP; нет любого из них — коннектор не настроен. Сбой БД → токен из env."""
    base_url = config.erp_base_url.strip().rstrip("/")
    if not base_url:
        return None
    token = ""
    if store.enabled:
        try:
            token = await store.get(ERP_SERVICE_TOKEN) or ""
        except Exception:
            logger.warning("erp_token_db_unavailable", exc_info=True)
    token = token or config.erp_service_token.get_secret_value()
    return ErpConnection(base_url=base_url, token=token) if token else None


async def erp_connector_configured(store: SecretsStore, config: Settings) -> bool:
    """Единственная точка проверки для режима жизненного цикла (`backoffice_mode`)."""
    return await resolve_connection(store, config) is not None
