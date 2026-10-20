"""Передача в бэк-офис и итог сделки из ERP (ADR-0022; CONTRACTS §2 `POST /clients/handoff`, §3).

Чистые функции без I/O. «Передан в бэк-офис» = стадия лида `customer`. Режим определяет код
по факту «коннектор ERP настроен» (`integrations/erp.erp_connector_configured`, ADR-0018):

- `local` — коннектора нет: «Сделать клиентом» как прежде (из `won`), итог сделки фиксирует CRM;
- `erp`   — коннектор есть: «Передать в бэк-офис» из работы (`in_progress`), итог сделки приходит
  событиями ERP `deal.won`/`deal.lost` и отражается в зеркале сделок, стадия лида не меняется.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from app.domain.stages import Stage

S = Stage


class BackofficeMode(StrEnum):
    LOCAL = "local"
    ERP = "erp"


def backoffice_mode(*, erp_connector_configured: bool) -> BackofficeMode:
    """Единственное место, где факт настройки коннектора превращается в режим жизненного цикла."""
    return BackofficeMode.ERP if erp_connector_configured else BackofficeMode.LOCAL


# Из каких стадий лида разрешена передача в бэк-офис (целевая стадия всегда `customer`).
# `customer` — повторная передача (идемпотентно: ничего не меняется) или смена компании.
HANDOFF_FROM: Final[dict[BackofficeMode, frozenset[Stage]]] = {
    BackofficeMode.LOCAL: frozenset({S.WON, S.CUSTOMER}),
    # `won` остаётся: лиды, закрытые в CRM до подключения ERP, тоже передаются.
    BackofficeMode.ERP: frozenset({S.IN_PROGRESS, S.WON, S.CUSTOMER}),
}

# События ERP с итогом сделки (CONTRACTS §3): меняют только зеркало сделок.
ERP_OUTCOME_EVENTS: Final = frozenset({"deal.won", "deal.lost"})


@dataclass(frozen=True, slots=True)
class HandoffDecision:
    mode: BackofficeMode
    from_stage: Stage
    allowed: bool
    changed: bool
    call_erp: bool
    reason: str | None = None

    @property
    def resync(self) -> bool:
        """Клиент уже привязан к лиду, но в ERP его ещё нет (стал клиентом в режиме `local`):
        в CRM ничего не меняется, в ERP уходит передача (I-14)."""
        return self.allowed and self.call_erp and not self.changed


def decide_handoff(
    current: Stage,
    mode: BackofficeMode,
    *,
    client_changed: bool = True,
    erp_synced: bool = True,
) -> HandoffDecision:
    """Можно ли передать лида в бэк-офис и что при этом происходит.

    `client_changed=False` — лид уже привязан к этому же клиенту: повторная передача
    ничего не меняет (`changed=False`), в ERP повторно не ходим (идемпотентность по
    `crm_client_id` держит и ERP, CONTRACTS §2). Смена компании у клиента — обычная передача.

    `erp_synced=False` — у клиента нет `erp_company_id`: он стал клиентом в режиме `local`,
    а коннектор ERP подключили позже. В режиме `erp` такого клиента передаём в ERP, хотя в CRM
    повторная передача ничего не меняет (`resync`); в режиме `local` ERP не вызывается никогда.
    """
    if current not in HANDOFF_FROM[mode]:
        return HandoffDecision(
            mode,
            current,
            allowed=False,
            changed=False,
            call_erp=False,
            reason=f"handoff from {current} is not allowed in {mode} mode",
        )
    changed = current != S.CUSTOMER or client_changed
    return HandoffDecision(
        mode,
        current,
        allowed=True,
        changed=changed,
        call_erp=mode == BackofficeMode.ERP and (changed or not erp_synced),
    )


def may_close_locally(mode: BackofficeMode, outcome: str) -> bool:
    """Итог лида из CRM («Сделка заключена»/«Закрыть отказом»).

    С коннектором ERP выигрыш решает бэк-офис (`deal.won`), фронт-офис может только
    отказать до передачи. Без коннектора — как прежде, оба итога.
    """
    if mode == BackofficeMode.LOCAL:
        return True
    return outcome == "lost"


@dataclass(frozen=True, slots=True)
class HandoffConsent:
    """Согласие лида на обработку данных в виде, который уходит в ERP (`consent`)."""

    given_at: datetime
    version: str


def handoff_consent(given_at: datetime | None, version: str | None) -> HandoffConsent | None:
    """Согласие для передачи в ERP — только то, что лид дал на самом деле (I-13).

    Время и версия берутся из лида. Нет любого из двух — `None`: согласие не выдумывается
    (ни «сейчас», ни «1.0»), передача невозможна, менеджер получает 422 «нет согласия».
    """
    if given_at is None or version is None or not version.strip():
        return None
    return HandoffConsent(given_at=given_at, version=version.strip())
