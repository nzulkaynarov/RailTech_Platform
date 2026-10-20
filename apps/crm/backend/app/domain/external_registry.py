"""Реестр внешних сервисов ансамбля (M3-CRM-12, ADR-0024; ORCHESTRATOR §3.13).

Чистые функции: каталог «всё, что интегрировано помимо CRM и ERP» — ключ, название и назначение
по-русски, кто пользуется, кто проверяет, как и как часто, где настраивается, есть ли выключатель.
Вендоры моделей — по одному на провайдера из алиасов LiteLLM. Правило §3.13: новый внешний сервис
принимается в код только со строкой здесь.

Выключатель вендора (ADR-0024): алиасы-чаты вендора перенаправляются на запасную модель
(`model_group_alias` LiteLLM), алиас эмбеддингов вендора блокируется; вендор запасной модели
выключить нельзя — перенаправлять некуда.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

Status = Literal["ok", "warn", "fail", "unknown", "off"]
Tier = Literal["cheap", "heavy"]
SwitchKind = Literal["vendor", "langfuse", "mail", "telegram"]
System = Literal["crm", "erp", "ensemble"]
Source = Literal["crm", "erp"]

FALLBACK_ALIAS: Final = "fallback-model"
EMBED_ALIAS: Final = "embed-model"
VENDOR_PREFIX: Final = "vendor."
ALIAS_TITLES: Final = {
    "dialog-model": "Диалог",
    "qualifier-model": "Квалификатор",
    "fallback-model": "Запасная модель",
    "embed-model": "Поиск по базе знаний",
    "judge-model": "Проверка качества",
    "intake-model": "ERP: разбор запроса",
    "match-model": "ERP: сопоставление с каталогом",
    "draft-model": "ERP: черновик КП",
    "enrich-model": "ERP: обогащение карточки",
}
VENDOR_TITLES: Final = {
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google Gemini",
    "openai": "OpenAI",
}
TLS_HOSTS: Final = ("crm", "erp", "cabinet")
ERP_REPORTED_REASON: Final = (
    "Нет данных: ERP пока не передаёт состояние своих внешних сервисов (появится с M3-ERP-06)"
)


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    key: str
    title: str
    purpose: str
    system: System
    source: Source
    check: str
    tiers: tuple[Tier, ...]
    fix_path: str | None
    switch: SwitchKind | None = None
    vendor: str | None = None


_TELEGRAM = ServiceSpec(
    key="telegram",
    title="Telegram Bot API",
    purpose="Клиентский бот, канал команды и личные уведомления сотрудникам",
    system="crm",
    source="crm",
    check="getMe (токен принят) и getWebhookInfo (очередь обновлений, ошибки доставки)",
    tiers=("cheap",),
    fix_path="/integrations?tab=bot",
    switch="telegram",
)
_LITELLM = ServiceSpec(
    key="litellm",
    title="Шлюз моделей (LiteLLM)",
    purpose="Единая точка вызова моделей ИИ для CRM и ERP: ключи, бюджеты, запасная модель",
    system="ensemble",
    source="crm",
    check="liveliness и readiness шлюза, без вызова моделей",
    tiers=("cheap",),
    fix_path="/models",
)
_AFTER_VENDORS: Final = (
    ServiceSpec(
        key="langfuse",
        title="Langfuse (журнал работы ИИ)",
        purpose="Трейсы диалогов и квалификатора: вопрос, ответ модели и стоимость",
        system="crm",
        source="crm",
        check="health и проверка ключей проекта (без записи трейсов)",
        tiers=("cheap",),
        fix_path=None,
        switch="langfuse",
    ),
    ServiceSpec(
        key="mail",
        title="Почтовый релей (SMTP)",
        purpose="Письма сотрудникам: приглашение, сброс пароля, оповещения о сбоях",
        system="crm",
        source="crm",
        check="журнал писем за 24 ч; раз в 15 мин — соединение и вход без отправки",
        tiers=("cheap", "heavy"),
        fix_path="/integrations?tab=mail",
        switch="mail",
    ),
    ServiceSpec(
        key="s3",
        title="Хранилище файлов (S3)",
        purpose="Документы клиентов, база знаний и вложения из Telegram",
        system="ensemble",
        source="crm",
        check="health; раз в 15 мин — занятое место по бакетам",
        tiers=("cheap", "heavy"),
        fix_path=None,
    ),
    ServiceSpec(
        key="docling",
        title="Распознавание документов (docling)",
        purpose="Текст из PDF и файлов Office для базы знаний и документов клиентов",
        system="crm",
        source="crm",
        check="health сервиса",
        tiers=("cheap",),
        fix_path=None,
    ),
    ServiceSpec(
        key="erp_sync",
        title="Синхронизация сотрудников с ERP",
        purpose="Доступ сотрудников к ERP: учётная запись при выдаче, отзыв сессий при снятии",
        system="ensemble",
        source="crm",
        check="итог последних задач провижининга и отзыва сессий (без запросов в ERP)",
        tiers=("cheap",),
        fix_path="/integrations?tab=erp",
    ),
    ServiceSpec(
        key="erp_handoff",
        title="Передача клиентов в ERP",
        purpose="«Передать в бэк-офис»: компания, контакты и заявка клиента появляются в ERP",
        system="ensemble",
        source="crm",
        check="итог последних передач клиентов и зависшие в очереди (без запросов в ERP)",
        tiers=("cheap",),
        fix_path="/clients",
    ),
    ServiceSpec(
        key="backup",
        title="Хранилище резервных копий",
        purpose="Ежедневная копия базы и файлов; восстановление после аварии",
        system="crm",
        source="crm",
        check="сервис копирования жив, возраст последней копии",
        tiers=("cheap",),
        fix_path="/backups",
    ),
)
_ERP_SERVICES: Final = (
    ("erp.cbu_rates", "Курсы ЦБ", "Курсы валют для цен и КП в ERP"),
    ("erp.customs_tariff", "Тариф и ТН ВЭД", "Таможенный тариф и коды ТН ВЭД для карточек товаров"),
    ("erp.mail", "Почта ERP", "Письма клиентам и сотрудникам бэк-офиса из ERP"),
    ("erp.sentry", "Sentry (ошибки ERP)", "Сбор ошибок приложения ERP"),
)


def vendor_key(provider: str) -> str:
    return f"{VENDOR_PREFIX}{provider}"


def vendor_of(key: str) -> str | None:
    return key.removeprefix(VENDOR_PREFIX) if key.startswith(VENDOR_PREFIX) else None


def vendor_aliases(providers: Mapping[str, str | None]) -> dict[str, list[str]]:
    """Провайдер → его алиасы в порядке ролей (`ALIAS_TITLES`), чужие алиасы — в конце."""
    order = list(ALIAS_TITLES)
    out: dict[str, list[str]] = {}
    for alias in sorted(providers, key=lambda a: (order.index(a) if a in order else 99, a)):
        provider = providers[alias]
        if provider:
            out.setdefault(provider, []).append(alias)
    return out


def _vendor_spec(provider: str, aliases: list[str]) -> ServiceSpec:
    roles = ", ".join(ALIAS_TITLES.get(a, a) for a in aliases)
    return ServiceSpec(
        key=vendor_key(provider),
        title=f"Модели ИИ: {VENDOR_TITLES.get(provider, provider)}",
        purpose=f"Роли: {roles}",
        system="ensemble",
        source="crm",
        check="журнал вызовов шлюза за 15 мин и 24 ч, бюджет провайдера — без вызова модели",
        tiers=("cheap", "heavy"),
        fix_path="/models",
        switch="vendor",
        vendor=provider,
    )


def _tls_spec(name: str) -> ServiceSpec:
    return ServiceSpec(
        key=f"tls.{name}",
        title=f"Сертификат {name}.",
        purpose=f"HTTPS для адреса {name}. — без него браузер не откроет систему",
        system="ensemble",
        source="crm",
        check="TLS-рукопожатие с проверкой цепочки, дней до окончания",
        tiers=("heavy",),
        fix_path="/settings?section=company" if name == "crm" else None,
    )


def _erp_spec(key: str, title: str, purpose: str) -> ServiceSpec:
    return ServiceSpec(
        key=key,
        title=title,
        purpose=purpose,
        system="erp",
        source="erp",
        check="состояние передаёт ERP (`externals[]` в integration /health, M3-ERP-06)",
        tiers=(),
        fix_path="/integrations?tab=erp",
    )


def registry(providers: Mapping[str, str | None]) -> list[ServiceSpec]:
    """Полный реестр в порядке показа; `providers` — алиас LiteLLM → провайдер."""
    vendors = [_vendor_spec(p, a) for p, a in vendor_aliases(providers).items()]
    return [
        _TELEGRAM,
        _LITELLM,
        *vendors,
        *_AFTER_VENDORS,
        *(_tls_spec(name) for name in TLS_HOSTS),
        *(_erp_spec(*row) for row in _ERP_SERVICES),
    ]


def find(specs: Iterable[ServiceSpec], key: str) -> ServiceSpec | None:
    return next((s for s in specs if s.key == key), None)


def switch_problem(vendor: str, providers: Mapping[str, str | None]) -> str | None:
    """Почему вендора нельзя снять с маршрута; None — можно."""
    if providers.get(FALLBACK_ALIAS) == vendor:
        return (
            "Этот провайдер обслуживает запасную модель — перенаправить вызовы некуда. "
            "Сначала смените провайдера запасной модели в «Модели ИИ»"
        )
    if providers.get(FALLBACK_ALIAS) is None:
        return "Запасная модель не настроена в шлюзе — перенаправить вызовы некуда («Модели ИИ»)"
    if vendor not in {p for p in providers.values() if p}:
        return "Этот провайдер сейчас не обслуживает ни одной роли — выключать нечего"
    return None


def redirects(disabled: Iterable[str], providers: Mapping[str, str | None]) -> dict[str, str]:
    """`model_group_alias` шлюза: алиасы-чаты выключенных вендоров → запасная модель."""
    off = set(disabled)
    return {
        alias: FALLBACK_ALIAS
        for alias, provider in sorted(providers.items())
        if provider in off and alias not in (FALLBACK_ALIAS, EMBED_ALIAS)
    }


def blocked_aliases(disabled: Iterable[str], providers: Mapping[str, str | None]) -> set[str]:
    """Алиасы, которые нельзя перенаправить (эмбеддинги): их deployment блокируются."""
    off = set(disabled)
    return {a for a, p in providers.items() if p in off and a == EMBED_ALIAS}


def switch_effect(vendor: str, providers: Mapping[str, str | None]) -> str:
    """Что произойдёт при выключении вендора — подпись в окне подтверждения."""
    moved = [ALIAS_TITLES.get(a, a) for a in redirects([vendor], providers)]
    blocked = [ALIAS_TITLES.get(a, a) for a in sorted(blocked_aliases([vendor], providers))]
    parts = []
    if moved:
        parts.append(f"на запасную модель перейдут: {', '.join(moved)}")
    if blocked:
        parts.append(f"остановится: {', '.join(blocked)}")
    return "; ".join(parts) or "роли этого провайдера не найдены"


SWITCH_EFFECTS: Final[dict[SwitchKind, str]] = {
    "telegram": (
        "Бот перестанет отвечать клиентам и писать команде: на любое сообщение клиент получит "
        "«Технические работы», карточки в канал и личные уведомления не уходят"
    ),
    "langfuse": "Трейсы диалогов и квалификатора перестанут записываться в Langfuse",
    "mail": "Письма сотрудникам будут копиться в очереди и уйдут после включения",
    "vendor": "",
}
