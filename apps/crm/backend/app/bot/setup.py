"""Сборка диалогового контура в процессе API: чекпоинтер, агент, сервис, бот."""

from collections.abc import AsyncIterator
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


@asynccontextmanager
async def bot_lifespan(
    container: Container,
    on_activity: ActivityHook | None = None,
    on_escalation: EscalationHook | None = None,
) -> AsyncIterator[BotRuntime | None]:
    config = container.settings
    if config.telegram_mode == "disabled" or not config.telegram_bot_token.get_secret_value():
        logger.warning("bot_disabled", mode=config.telegram_mode)
        yield None
        return
    async with checkpointer(container) as saver:
        agent = DialogAgent(McpToolClient(config), ChatModel(container.llm, "dialog-model"), saver)
        conversation = ConversationService(
            container.session_factory,
            container.settings_service,
            agent,
            config.agent_context_key_bytes,
            on_activity=on_activity,
            on_escalation=on_escalation,
        )
        dispatcher = build_dispatcher(
            container.session_factory,
            conversation,
            container.settings_service,
            container.storage,
            config.s3_bucket_attachments,
        )
        runtime = BotRuntime.create(config, dispatcher)
        await runtime.start()
        try:
            yield runtime
        finally:
            await runtime.stop()
