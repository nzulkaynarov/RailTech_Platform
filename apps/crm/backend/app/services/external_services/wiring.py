"""Сборка прохода проверок центра внешних сервисов из контейнера процесса (ADR-0024)."""

from typing import TYPE_CHECKING

from app.integrations.litellm_spend import LiteLLMSpendLogs
from app.services.external_services.alerts import AlertSender
from app.services.external_services.checks import ExternalChecks
from app.services.external_services.collector import Collector, Deps

if TYPE_CHECKING:
    from app.container import Container


def build_checks(c: "Container") -> ExternalChecks:
    async def erp_url() -> str:
        return (await c.erp_connector.resolution()).base_url

    async def erp_configured() -> bool:
        return (await c.erp_connector.resolution()).connection is not None

    deps = Deps(
        config=c.settings,
        settings=c.settings_service,
        secrets=c.secrets_store,
        sessions=c.session_factory,
        mail=c.mail_service,
        storage=c.storage,
        backups=c.backup_service,
        admin=c.litellm_admin,
        spend_logs=LiteLLMSpendLogs(c.settings.litellm_base_url, c.settings.litellm_api_key),
        catalog=c.model_catalog,
        erp_url=erp_url,
        defaults=c.settings.litellm_models_path,
        erp_configured=erp_configured,
        erp_facts=c.erp_connector.health_facts,
    )
    alerts = AlertSender(
        c.session_factory,
        c.settings_service,
        c.telegram_bot,
        c.mail_service,
        c.switch_board.is_disabled,
    )
    return ExternalChecks(
        c.session_factory,
        Collector(deps),
        alerts,
        c.settings_service,
        c.switch_board,
        reconcile=c.external_switches.reconcile,
        on_recorded=c.external_view.invalidate,
        causes=c.external_view.causes,
    )
