"""«Состояние системы» (admin): зависимости, модели, бюджет ИИ, бот, очередь, ERP, секреты."""

import asyncio
from collections.abc import Awaitable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, require
from app.api.health import get_readiness
from app.container import Container
from app.domain import system_status as rules
from app.domain.external_incidents import SUMMARY_KEY, SUMMARY_TITLE
from app.domain.system_status import STAND_EXPECTED, BotFacts, Component, ErpFacts, ordered
from app.integrations.telegram import resolve_token
from app.schemas.system import ComponentStatusOut, SystemStatusOut
from app.security.principal import Principal
from app.services.readiness import ReadinessService
from app.services.system_status import SOURCE_TIMEOUT_S, SystemStatusService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])

_SEVERITY = ("ok", "unknown", "warn", "fail")


async def _within[T](name: str, call: Awaitable[T], fallback: T) -> tuple[T, bool]:
    """Результат источника и «уложился»; медленный или упавший источник даёт `fallback`."""
    try:
        return await asyncio.wait_for(call, SOURCE_TIMEOUT_S), True
    except Exception as exc:  # noqa: BLE001 — «Состояние» не падает из-за одного источника
        logger.warning("system_status_source_failed", source=name, error=type(exc).__name__)
        return fallback, False


async def _bot_facts(container: Container) -> BotFacts | None:
    """Бот живёт в `crm-bot` (S0-4): факты — из его записи в БД, а не из памяти процесса API."""
    try:
        snapshot = await container.bot_state.snapshot()
    except Exception as exc:  # noqa: BLE001 — «Состояние системы» не падает из-за статуса бота
        logger.warning("bot_state_unavailable", error=type(exc).__name__)
        return None
    if snapshot is None:
        return BotFacts(False, "none", "bot_process_never_started")
    if not snapshot.alive:
        return BotFacts(False, snapshot.source, "bot_process_down")
    return BotFacts(snapshot.running, snapshot.source, snapshot.last_error)


async def collect_components(
    container: Container, readiness: ReadinessService, now: datetime, *, probe_erp: bool = True
) -> list[Component]:
    """Один источник здоровья для «Состояния», индикатора в шапке и чек-листа настройки.

    `probe_erp=False` — без живой пробы ERP (до 5 с при устаревшем кэше): чек-листу нужны
    только бот и модели, а зависшая ERP не должна задерживать весь ответ (W13C-F1)."""

    async def token_source() -> str:
        return (await resolve_token(container.secrets_store, container.settings))[1]

    async def erp_facts() -> ErpFacts | None:
        return await container.erp_connector.health_facts() if probe_erp else None

    # Независимые источники идут вместе, каждый со своим пределом ожидания (W15b-1): сумма задержек
    # раньше превышала ожидание BFF, и карточка «Состояние системы» оставалась в загрузке.
    (
        (bot, _),
        (source, _),
        (erp, erp_in_time),
        (ai_budget, _),
        (summary, summary_ok),
    ) = await asyncio.gather(
        _within("bot", _bot_facts(container), None),
        _within("token", token_source(), "none"),
        _within("erp", erp_facts(), None),
        _within("ai_budget", container.ai_spend.today_facts(), None),
        _within("external_services", container.external_view.summary(now), None),
    )
    has_token = source in ("db", "env")
    service = SystemStatusService(
        container.session_factory,
        container.settings_service,
        container.settings,
        readiness,
        container.backup_service,
    )
    components = await service.collect(
        now, bot, token_configured=has_token, erp=erp, ai_budget=ai_budget
    )
    if probe_erp and not erp_in_time:
        # ERP не ответила в срок: «не проверено», а не «коннектор не настроен».
        components = [c for c in components if c.key != "erp"]
        components.append(rules.not_checked("erp", rules.ERP_TITLE, now, "ERP"))
    if summary is not None:
        # Сводка центра внешних сервисов (M3-CRM-12): подробности — на «Внешних сервисах».
        components.append(summary)
    elif not summary_ok:
        components.append(
            rules.not_checked(SUMMARY_KEY, SUMMARY_TITLE, now, "центр внешних сервисов")
        )
    return ordered(components)


@router.get("/status", response_model=SystemStatusOut)
async def system_status(
    _: Annotated[Principal, Depends(require("system", "read"))],
    container: ContainerDep,
    readiness: Annotated[ReadinessService, Depends(get_readiness)],
) -> SystemStatusOut:
    """Только чтение: моделей не вызывает, их здоровье — из последней проверки монитора.

    Компоненты отсортированы: сбой → предупреждение → неизвестно → норма.
    """
    now = datetime.now(UTC)
    components = await collect_components(container, readiness, now)
    stand = container.settings.is_stand
    expected = {
        c.key
        for c in components
        if stand and c.key in STAND_EXPECTED and c.status in ("warn", "fail")
    }
    worst = max(
        (c.status for c in components if c.key not in expected),
        key=_SEVERITY.index,
        default="unknown",
    )
    return SystemStatusOut(
        status=worst,
        checked_at=now,
        components=[
            ComponentStatusOut(**asdict(c), expected_on_stand=c.key in expected) for c in components
        ],
    )
