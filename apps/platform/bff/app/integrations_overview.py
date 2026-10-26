"""Обзор экрана «Внешние интеграции»: карточки со статусом и «Требует внимания» (W13-A1).

BFF не проверяет сервисы и не решает, что исправно: статусы пятью уровнями (`ok`, `warn`,
`fail`, `unknown`, `off`) приходят из реестра внешних сервисов CRM (ADR-0024 CRM), состояния
моделей, бэкапов и системы — из ответов CRM. Здесь только свод:

- уровень карточки — худший из уровней её сервисов (`fail` > `warn` > `unknown` > `ok`); `off`
  не ухудшает, а у карточки, где все сервисы `off`, карточка `off` («не подключено»);
- пометка карточки (`note`) — машинный код, фразу собирает интерфейс на языке сотрудника;
- «Требует внимания» — то, что не в норме или ещё не подключено: сначала сбои, затем
  предупреждения, затем неподключённое.

Часть данных, которую CRM не отдала (нет права в CRM или не ответила), карточку не роняет:
`access = forbidden | unavailable`, статус `unknown`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.clients.crm_integrations import fix_card_of
from app.schemas_integrations import (
    Access,
    AiModelList,
    AttentionItem,
    AttentionKind,
    BackupsStatus,
    CardKey,
    ErpConnector,
    ExternalService,
    ExternalServiceList,
    IntegrationCard,
    IntegrationsOverview,
    Level,
    Note,
    Severity,
    SpendReport,
    SystemStatus,
    TelegramConnector,
)

PartState = Literal["ok", "forbidden", "unavailable"]

ERP_KEYS = frozenset({"erp_sync", "erp_handoff", "erp_events"})
BUDGET_WARN_RATIO = (
    0.8  # как в реестре CRM: расход ≥ 80 % бюджета провайдера — предупреждение, ≥ 100 % — сбой
)
STORAGE_KEYS = frozenset({"s3", "backup"})
_RANK: dict[str, int] = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
_SEVERITY_ORDER: dict[Severity, int] = {"fail": 0, "warn": 1, "setup": 2}
CARD_ORDER: tuple[CardKey, ...] = (
    "erp",
    "telegram",
    "mail",
    "services",
    "models",
    "spend",
    "storage",
    "system",
)


@dataclass(frozen=True)
class Part[T]:
    """Одна часть обзора: ответ CRM или причина, по которой его нет."""

    state: PartState
    data: T | None = None

    @property
    def ok(self) -> bool:
        return self.state == "ok" and self.data is not None


@dataclass(frozen=True)
class Parts:
    services: Part[ExternalServiceList]
    system: Part[SystemStatus]
    erp: Part[ErpConnector]
    telegram: Part[TelegramConnector]
    models: Part[AiModelList]
    backups: Part[BackupsStatus]
    spend: Part[SpendReport]

    def all(self) -> tuple[Part[Any], ...]:
        return (
            self.services,
            self.system,
            self.erp,
            self.telegram,
            self.models,
            self.backups,
            self.spend,
        )


def worst(levels: list[Level]) -> Level:
    """Худший уровень; `off` не считается, все `off` — `off`."""
    active = [level for level in levels if level != "off"]
    if not active:
        return "off"
    return max(active, key=lambda level: _RANK[level])


def _latest(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _access(*needed: Part[Any]) -> Access:
    if any(p.ok for p in needed):
        return "ok"
    return "forbidden" if any(p.state == "forbidden" for p in needed) else "unavailable"


def _is_model_service(service: ExternalService) -> bool:
    return service.key == "litellm" or service.key.startswith("vendor.")


def _by_key(services: list[ExternalService], keys: frozenset[str]) -> list[ExternalService]:
    return [s for s in services if s.key in keys]


def _problems(services: list[ExternalService]) -> list[ExternalService]:
    return [s for s in services if s.status in ("fail", "warn")]


def _paused(service: ExternalService | None) -> bool:
    return service is not None and service.switch is not None and service.switch.disabled


def _blank(key: CardKey, access: Access) -> IntegrationCard:
    return IntegrationCard(
        key=key,
        status="unknown",
        access=access,
        note="no_data",
        count=None,
        amount_usd=None,
        last_activity_at=None,
    )


def _card(
    key: CardKey,
    status: Level,
    note: Note,
    *,
    count: int | None = None,
    amount: float | None = None,
    last: datetime | None = None,
) -> IntegrationCard:
    return IntegrationCard(
        key=key,
        status=status,
        access="ok",
        note=note,
        count=count,
        amount_usd=amount,
        last_activity_at=last,
    )


def _services_of(parts: Parts) -> list[ExternalService]:
    return parts.services.data.items if parts.services.data else []


def _erp_card(parts: Parts) -> IntegrationCard:
    access = _access(parts.erp, parts.services)
    if access != "ok":
        return _blank("erp", access)
    services = _by_key(_services_of(parts), ERP_KEYS)
    connector = parts.erp.data
    last = _latest(
        *(s.checked_at for s in services), connector.token_updated_at if connector else None
    )
    if connector is not None and not connector.configured:
        return _card("erp", "off", "not_configured", last=last)
    status = worst([s.status for s in services]) if services else "unknown"
    problems = _problems(services)
    if problems:
        return _card("erp", status, "problems", count=len(problems), last=last)
    if connector is not None and connector.rotation_pending:
        return _card("erp", status, "rotation_pending", last=last)
    return _card("erp", status, "all_ok" if services else "no_data", last=last)


def _telegram_card(parts: Parts) -> IntegrationCard:
    access = _access(parts.telegram, parts.services)
    if access != "ok":
        return _blank("telegram", access)
    service = next((s for s in _services_of(parts) if s.key == "telegram"), None)
    connector = parts.telegram.data
    last = _latest(
        service.checked_at if service else None, connector.updated_at if connector else None
    )
    status: Level = service.status if service else "unknown"
    if connector is not None and not connector.configured:
        return _card("telegram", "off", "not_configured", last=last)
    if service is not None and service.status == "off":
        return _card("telegram", "off", "not_configured", last=last)
    if _paused(service):
        return _card("telegram", status, "paused", last=last)
    if service is not None and service.status in ("fail", "warn"):
        return _card("telegram", status, "problems", count=1, last=last)
    if connector is not None and connector.configured and not connector.running:
        return _card("telegram", worst([status, "warn"]), "bot_not_running", last=last)
    return _card("telegram", status, "all_ok" if service else "no_data", last=last)


def _mail_card(parts: Parts) -> IntegrationCard:
    access = _access(parts.services)
    if access != "ok":
        return _blank("mail", access)
    service = next((s for s in _services_of(parts) if s.key == "mail"), None)
    if service is None:
        return _card("mail", "unknown", "no_data")
    last = service.checked_at
    if service.status == "off":
        return _card("mail", "off", "not_configured", last=last)
    if _paused(service):
        return _card("mail", service.status, "paused", last=last)
    if service.status in ("fail", "warn"):
        return _card("mail", service.status, "problems", count=1, last=last)
    return _card("mail", service.status, "all_ok", last=last)


def _services_card(parts: Parts) -> IntegrationCard:
    if not parts.services.ok or parts.services.data is None:
        return _blank("services", _access(parts.services))
    data = parts.services.data
    status = worst([s.status for s in data.items])
    problems = _problems(data.items)
    if problems:
        return _card("services", status, "problems", count=len(problems), last=data.checked_at)
    if data.summary.disabled:
        return _card(
            "services", status, "paused", count=data.summary.disabled, last=data.checked_at
        )
    note: Note = "all_ok" if data.items and status != "unknown" else "no_data"
    return _card("services", status, note, last=data.checked_at)


def _model_level(health: str) -> Level:
    return {"ok": "ok", "problem": "fail"}.get(health, "unknown")  # type: ignore[return-value]


def _models_card(parts: Parts) -> IntegrationCard:
    access = _access(parts.models, parts.services)
    if access != "ok":
        return _blank("models", access)
    registry = [s for s in _services_of(parts) if _is_model_service(s)]
    models = parts.models.data.items if parts.models.data else []
    levels: list[Level] = [s.status for s in registry] + [_model_level(m.health) for m in models]
    status = worst(levels) if levels else "unknown"
    broken = [m for m in models if m.health == "problem"]
    count = len(broken) + len(_problems(registry))
    last = _latest(*(s.checked_at for s in registry), *(m.checked_at for m in models))
    if count:
        return _card("models", status, "problems", count=count, last=last)
    return _card("models", status, "all_ok" if levels else "no_data", last=last)


def _budget_ratio(spent: float, limit: float) -> float | None:
    return spent / limit if limit > 0 else None


def _spend_level(report: SpendReport) -> tuple[Level, Note]:
    ratios = [
        r for p in report.providers if (r := _budget_ratio(p.spent_usd, p.limit_usd)) is not None
    ]
    top = max(ratios, default=0.0)
    if top >= 1:
        return "fail", "budget_over"
    if top >= BUDGET_WARN_RATIO:
        return "warn", "budget_near"
    return "ok", "all_ok"


def _spend_card(parts: Parts) -> IntegrationCard:
    if not parts.spend.ok or parts.spend.data is None:
        return _blank("spend", _access(parts.spend))
    status, note = _spend_level(parts.spend.data)
    return _card("spend", status, note, amount=parts.spend.data.today_usd)


def _backup_state(backups: BackupsStatus) -> tuple[Level, Note | None]:
    if backups.error is not None or not backups.available:
        return "warn", "no_data" if backups.error is None else "problems"
    if backups.last_success_at is None:
        return "warn", "no_backups"
    if backups.stale:
        return "warn", "backup_stale"
    return "ok", None


def _storage_card(parts: Parts) -> IntegrationCard:
    access = _access(parts.backups, parts.services)
    if access != "ok":
        return _blank("storage", access)
    services = _by_key(_services_of(parts), STORAGE_KEYS)
    levels: list[Level] = [s.status for s in services]
    backups = parts.backups.data
    note: Note | None = None
    if backups is not None:
        level, note = _backup_state(backups)
        # Бэкап — ещё и сервис реестра `backup`: свод не улучшает уровень, который поставила CRM.
        levels.append(level)
    status = worst(levels) if levels else "unknown"
    last = _latest(backups.last_success_at if backups else None, *(s.checked_at for s in services))
    if note in ("no_backups", "backup_stale"):
        return _card("storage", status, note, last=last)
    problems = _problems(services)
    if problems or note == "problems":
        return _card("storage", status, "problems", count=max(len(problems), 1), last=last)
    return _card("storage", status, "all_ok" if levels else "no_data", last=last)


def _system_card(parts: Parts) -> IntegrationCard:
    if not parts.system.ok or parts.system.data is None:
        return _blank("system", _access(parts.system))
    data = parts.system.data
    bad = [c for c in data.components if c.status in ("fail", "warn")]
    if bad:
        return _card("system", data.status, "problems", count=len(bad), last=data.checked_at)
    return _card("system", data.status, "all_ok", last=data.checked_at)


# --- «Требует внимания» -------------------------------------------------------------------


def _item(
    item_id: str,
    card: CardKey,
    severity: Severity,
    kind: AttentionKind,
    subject: str | None = None,
    detail: str | None = None,
) -> AttentionItem:
    return AttentionItem(
        id=item_id, card=card, severity=severity, kind=kind, subject=subject, detail=detail
    )


def _sentence(*parts: str | None) -> str | None:
    """Итог проверки и подсказка CRM одной строкой; между предложениями — точка, если её нет."""
    texts = [p.strip() for p in parts if p and p.strip()]
    joined = ""
    for text in texts:
        if joined and joined[-1] not in ".!?…":
            joined += "."
        joined = f"{joined} {text}" if joined else text
    return joined or None


def _service_items(parts: Parts) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for service in _services_of(parts):
        card: CardKey = fix_card_of_service(service)
        if _paused(service):
            items.append(
                _item(
                    f"paused:{service.key}",
                    card,
                    "warn",
                    "paused",
                    service.title,
                    service.switch.reason if service.switch else None,
                )
            )
        elif service.status in ("fail", "warn"):
            severity: Severity = "fail" if service.status == "fail" else "warn"
            items.append(
                _item(
                    f"service:{service.key}",
                    card,
                    severity,
                    "service",
                    service.title,
                    _sentence(service.summary, service.hint),
                )
            )
    return items


def fix_card_of_service(service: ExternalService) -> CardKey:
    """Карточка, где исправляется сервис; нет подсказки — общий реестр."""
    return service.fix_card or "services"


def _setup_items(parts: Parts) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    services = {s.key: s for s in _services_of(parts)}
    erp = parts.erp.data
    if erp is not None:
        if not erp.configured:
            items.append(_item("setup:erp", "erp", "setup", "not_configured"))
        elif erp.rotation_pending:
            items.append(_item("rotation:erp", "erp", "warn", "rotation_pending"))
    telegram = parts.telegram.data
    if telegram is not None:
        if not telegram.configured:
            items.append(_item("setup:telegram", "telegram", "setup", "not_configured"))
        elif not telegram.running:
            items.append(
                _item(
                    "bot:telegram", "telegram", "warn", "bot_not_running", None, telegram.last_error
                )
            )
    elif services.get("telegram") is not None and services["telegram"].status == "off":
        items.append(_item("setup:telegram", "telegram", "setup", "not_configured"))
    mail = services.get("mail")
    if mail is not None and mail.status == "off":
        items.append(_item("setup:mail", "mail", "setup", "not_configured"))
    return items


def _model_items(parts: Parts) -> list[AttentionItem]:
    models = parts.models.data.items if parts.models.data else []
    return [
        _item(f"model:{m.alias}", "models", "fail", "model_problem", m.alias, m.health_detail)
        for m in models
        if m.health == "problem"
    ]


def _storage_items(parts: Parts) -> list[AttentionItem]:
    backups = parts.backups.data
    if backups is None:
        return []
    level, note = _backup_state(backups)
    if level == "ok" or note is None:
        return []
    return [_item("backup:stale", "storage", "warn", "backup_stale", None, backups.error)]


def _system_items(parts: Parts) -> list[AttentionItem]:
    data = parts.system.data
    if data is None:
        return []
    return [
        _item(
            f"component:{c.key}",
            "system",
            "fail" if c.status == "fail" else "warn",
            "component",
            c.title,
            c.reason,
        )
        for c in data.components
        if c.status in ("fail", "warn")
    ]


def _spend_items(parts: Parts) -> list[AttentionItem]:
    report = parts.spend.data
    if report is None:
        return []
    items: list[AttentionItem] = []
    for provider in report.providers:
        ratio = _budget_ratio(provider.spent_usd, provider.limit_usd)
        if ratio is None or ratio < BUDGET_WARN_RATIO:
            continue
        over = ratio >= 1
        items.append(
            _item(
                f"budget:{provider.provider}",
                "spend",
                "fail" if over else "warn",
                "budget_over" if over else "budget_near",
                provider.provider,
                f"{provider.spent_usd:.2f} / {provider.limit_usd:.2f} USD",
            )
        )
    return items


def build_overview(parts: Parts, *, now: datetime | None = None) -> IntegrationsOverview:
    builders = {
        "erp": _erp_card,
        "telegram": _telegram_card,
        "mail": _mail_card,
        "services": _services_card,
        "models": _models_card,
        "spend": _spend_card,
        "storage": _storage_card,
        "system": _system_card,
    }
    cards = [builders[key](parts) for key in CARD_ORDER]
    attention = [
        *_service_items(parts),
        *_setup_items(parts),
        *_model_items(parts),
        *_storage_items(parts),
        *_system_items(parts),
        *_spend_items(parts),
    ]
    # Одна беда может прийти из двух источников (сервис реестра и компонент состояния):
    # оставляем первую запись с этим id.
    unique = list({item.id: item for item in attention}.values())
    unique.sort(key=lambda item: _SEVERITY_ORDER[item.severity])
    return IntegrationsOverview(checked_at=now or datetime.now(UTC), cards=cards, attention=unique)


__all__ = ["Part", "Parts", "build_overview", "fix_card_of", "worst"]
