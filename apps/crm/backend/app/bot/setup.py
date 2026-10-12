"""Сборка диалогового контура в процессе API: чекпоинтер, агент, сервис, бот."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agents.dialog.graph import DialogAgent
from app.agents.llm import ChatModel
from app.agents.mcp_client import McpToolClient
from app.bot.runtime import BotRuntime, build_dispatcher
from app.container import Container
from app.security.rbac import Rbac
from app.services.budget import BudgetedModel, BudgetGuard
from app.services.conversation import ActivityHook, ConversationService, EscalationHook

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def checkpointer(container: Container) -> AsyncIterator[AsyncPostgresSaver]:
    """`PostgresSaver` LangGraph (SPEC §2); таблицы создаёт `setup()` идемпотентно."""
    pool = AsyncConnectionPool(
        container.settings.libpq_dsn,
        open=False,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        yield saver
    finally:
        await pool.close()


def build_conversation(
    container: Container,
    saver: AsyncPostgresSaver,
    on_activity: ActivityHook | None = None,
    on_escalation: EscalationHook | None = None,
    on_lead_message: ActivityHook | None = None,
) -> ConversationService:
    """Диалоговый контур бота: BudgetGuard → модель, MCP-инструменты, чекпоинтер."""
    model = BudgetedModel(
        ChatModel(container.llm, "dialog-model"),
        ChatModel(container.llm, "fallback-model"),
        BudgetGuard(container.session_factory, container.settings_service),
    )
    agent = DialogAgent(McpToolClient(container.settings), model, saver)
    return ConversationService(
        container.session_factory,
        container.settings_service,
        agent,
        container.settings.agent_context_key_bytes,
        on_activity=on_activity,
        on_escalation=on_escalation,
        erase_attachments=_attachments_eraser(container),
        on_lead_message=on_lead_message,
    )


def _attachments_eraser(container: Container) -> Callable[[list[str]], Awaitable[None]]:
    async def erase(keys: list[str]) -> None:
        for key in keys:
            await container.storage.delete(container.settings.s3_bucket_attachments, key)

    return erase


@asynccontextmanager
async def bot_lifespan(
    container: Container,
    on_activity: ActivityHook | None = None,
    on_escalation: EscalationHook | None = None,
    on_lead_message: ActivityHook | None = None,
) -> AsyncIterator[BotRuntime | None]:
    config = container.settings
    if config.telegram_mode == "disabled" or not config.telegram_bot_token.get_secret_value():
        logger.warning("bot_disabled", mode=config.telegram_mode)
        yield None
        return
    async with checkpointer(container) as saver:
        conversation = build_conversation(
            container, saver, on_activity, on_escalation, on_lead_message
        )
        rbac = await Rbac.create(container.engine, config.casbin_dir)
        dispatcher = build_dispatcher(
            container.session_factory,
            conversation,
            container.settings_service,
            container.storage,
            config.s3_bucket_attachments,
            leads=container.lead_service,
            rbac=rbac,
        )
        runtime = BotRuntime.create(config, dispatcher)
        await runtime.start()
        try:
            yield runtime
        finally:
            await runtime.stop()
