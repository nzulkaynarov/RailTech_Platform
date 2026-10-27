"""Сбор фактов для экрана «Состояние системы» (аудит 2026-10-12 §3 п. 6).

Только чтение: готовность зависимостей (`ReadinessService`), последние результаты монитора
(`system_alerts`), очередь Procrastinate и конфигурация. Платных вызовов моделей нет.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import system_status as rules
from app.domain.system_status import (
    AiBudgetFacts,
    AlertRow,
    BackupFacts,
    BotFacts,
    Component,
    ErpFacts,
    QueueFacts,
)
from app.models.system import SystemAlert
from app.repositories import monitoring as repo
from app.services import backups as backup_rules
from app.services.backups import BackupReader
from app.services.readiness import ReadinessService
from app.services.settings import SettingsService

REQUIRED_SECRETS = (
    "postgres_password",
    "s3_access_key",
    "s3_secret_key",
    "litellm_api_key",
    "telegram_bot_token",
    "jwt_secret",
    "agent_context_key",
)
STALLED = text(
    """
    SELECT count(*) FROM procrastinate_jobs j
    WHERE j.status = 'doing' AND (
        SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id AND e.type = 'started'
    ) < :before
    """
)


def missing_secrets(config: Settings, *, token_elsewhere: bool = False) -> list[str]:
    """Имена переменных окружения без значения; сами значения наружу не уходят.

    Токен бота, сохранённый в «Подключениях» (БД, ADR-0018), закрывает TELEGRAM_BOT_TOKEN.
    """
    names = [n for n in REQUIRED_SECRETS if not (token_elsewhere and n == "telegram_bot_token")]
    if config.telegram_mode == "webhook":
        names.append("telegram_webhook_secret")
    missing = []
    for name in names:
        value = getattr(config, name)
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        if not raw:
            missing.append(name.upper())
    return missing


class SystemStatusService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        config: Settings,
        readiness: ReadinessService,
        backups: BackupReader | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._config = config
        self._readiness = readiness
        self._backups = backups

    async def collect(
        self,
        now: datetime,
        bot: BotFacts | None,
        *,
        token_configured: bool,
        erp: ErpFacts | None = None,
        ai_budget: Sequence[AiBudgetFacts] | None = None,
    ) -> list[Component]:
        """Единый источник здоровья: «Состояние», индикатор в шапке и чек-лист настройки.

        `erp` — итог кэшированной пробы коннектора (M3-CRM-02); None — коннектор не настроен.
        `ai_budget` — расход ИИ сегодня по системам из журнала LiteLLM (M3-CRM-09, кэш 60 с);
        None — журнал недоступен.
        """
        report = await self._readiness.check()
        components = rules.dependencies(report.checks, now)
        if report.checks.get("database", False):
            cfg = await self._settings.get()
            alerts, facts = await self._db_facts(now)
            components += rules.models(alerts)
            components.append(rules.budget(alerts, now))
            components.append(rules.queue(facts, now))
            components.append(rules.channel(cfg.notifications.channel_id, now))
            platform = rules.PlatformUrlFacts(
                self._config.platform_base_url, self._config.app_env == "prod"
            )
            components.append(rules.crm_url(cfg.company.crm_base_url, now, platform))
        components.append(rules.bot(bot, self._config.telegram_mode, now))
        components.append(await self._backup(now))
        components.append(rules.erp(erp or ErpFacts(configured=False), now))
        components.append(rules.ai_budget(ai_budget, now))
        missing = missing_secrets(self._config, token_elsewhere=token_configured)
        has_key = bool(self._config.secrets_key.get_secret_value())
        components.append(rules.secrets(missing, now, secrets_key=has_key))
        return rules.ordered(components)

    async def _db_facts(self, now: datetime) -> tuple[list[AlertRow], QueueFacts]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(SystemAlert))).all()
            stalled_before = now - timedelta(minutes=rules.STALLED_MINUTES)
            stalled = int((await session.execute(STALLED, {"before": stalled_before})).scalar_one())
            failed = await repo.failed_tasks(session, now - timedelta(hours=1))
            facts = QueueFacts(
                waiting=await repo.queue_size(session),
                stalled=stalled,
                failed_last_hour=sum(failed.values()),
            )
        alerts = [AlertRow(r.key, r.active, r.detail, r.updated_at) for r in rows]
        return alerts, facts

    async def _backup(self, now: datetime) -> Component:
        if self._backups is None:
            return rules.backup(now, BackupFacts(False, False, None, None))
        state = await self._backups.status(limit=0)
        return rules.backup(now, backup_rules.facts(state, now))
