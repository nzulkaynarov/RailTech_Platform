"""Сборка диалогового контура в процессе API: чекпоинтер, агент, сервис, бот."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import structlog
from aiogram import Dispatcher
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agents.dialog.graph import DialogAgent
from app.agents.llm import ChatModel
from app.agents.mcp_client import McpToolClient
from app.bot.runtime import build_dispatcher
from app.bot.supervisor import BotSupervisor
from app.container import Container
from app.integrations.telegram import TokenSource, resolve_token
from app.security.rbac import Rbac
from app.services.budget import BudgetedModel
from app.services.client_bot import ClientBotService
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
    usage = container.usage_recorder
    model = BudgetedModel(
        ChatModel(container.llm, "dialog-model", usage=usage),
        ChatModel(container.llm, "fallback-model", usage=usage, purpose="dialog"),
        container.budget_guard,
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


class SandboxConversation:
    """Диалоговый контур песочницы «Проверить бота»: тот же `build_conversation`, без хуков.

    Чекпоинтер открывается при первом сообщении из CRM, закрывается с процессом API.
    """

    def __init__(self, container: Container) -> None:
        self._container = container
        self._stack = AsyncExitStack()
        self._service: ConversationService | None = None
        self._lock = asyncio.Lock()

    async def __call__(self) -> ConversationService:
        async with self._lock:
            if self._service is None:
                saver = await self._stack.enter_async_context(checkpointer(self._container))
                self._service = build_conversation(self._container, saver)
            return self._service

    async def aclose(self) -> None:
        self._service = None
        await self._stack.aclose()


def build_client_bot(
    container: Container, on_escalation: EscalationHook | None = None
) -> ClientBotService:
    """Меню клиента, /docs (ссылка S3 на 10 минут, как у docs-mcp), /request, номер."""
    bucket = container.settings.s3_bucket_documents

    async def presign(key: str, ttl_s: int) -> str:
        return await container.storage.presigned_get(bucket, key, ttl_s)

    return ClientBotService(
        container.session_factory, container.settings_service, presign, on_escalation
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
) -> AsyncIterator[BotSupervisor | None]:
    """Супервизор бота: токен — из «Подключений» (БД) или env; смена токена — без рестарта API."""
    config = container.settings
    if config.telegram_mode == "disabled":
        logger.warning("bot_disabled", mode=config.telegram_mode)
        yield None
        return
    async with AsyncExitStack() as stack:

        async def make_dispatcher() -> Dispatcher:
            saver = await stack.enter_async_context(checkpointer(container))
            conversation = build_conversation(
                container, saver, on_activity, on_escalation, on_lead_message
            )
            rbac = await Rbac.create(container.engine, config.casbin_dir)
            return build_dispatcher(
                container.session_factory,
                conversation,
                container.settings_service,
                container.storage,
                config.s3_bucket_attachments,
                leads=container.lead_service,
                rbac=rbac,
                client_bot=build_client_bot(container, on_escalation),
            )

        async def resolve() -> tuple[str, TokenSource]:
            return await resolve_token(container.secrets_store, config)

        supervisor = BotSupervisor(config, resolve, make_dispatcher)
        # Бот стартует в фоне: недоступный Telegram не должен держать старт CRM (иначе сбой
        # Telegram = недоступная CRM); причина видна в «Подключениях» и «Состоянии».
        starting = asyncio.create_task(supervisor.start(), name="bot_supervisor_start")
        try:
            yield supervisor
        finally:
            starting.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await starting
            await supervisor.stop()
