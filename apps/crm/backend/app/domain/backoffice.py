"""Передача в бэк-офис и итог сделки из ERP (ADR-0022; CONTRACTS §2 `POST /clients/handoff`, §3).

Чистые функции без I/O. «Передан в бэк-офис» = стадия лида `customer`. Режим определяет код
по факту «коннектор ERP настроен» (`integrations/erp.erp_connector_configured`, ADR-0018):

- `local` — коннектора нет: «Сделать клиентом» как прежде (из `won`), итог сделки фиксирует CRM;
- `erp`   — коннектор есть: «Передать в бэк-офис» из работы (`in_progress`), итог сделки приходит
  событиями ERP `deal.won`/`deal.lost` и отражается в зеркале сделок, стадия лида не меняется.
"""

from dataclasses import dataclass
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


def decide_handoff(
    current: Stage, mode: BackofficeMode, *, client_changed: bool = True
) -> HandoffDecision:
    """Можно ли передать лида в бэк-офис и что при этом происходит.

    `client_changed=False` — лид уже привязан к этому же клиенту: повторная передача
    ничего не меняет (`changed=False`), в ERP повторно не ходим (идемпотентность по
    `crm_client_id` держит и ERP, CONTRACTS §2). Смена компании у клиента — обычная передача.
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
        call_erp=mode == BackofficeMode.ERP and changed,
    )


def may_close_locally(mode: BackofficeMode, outcome: str) -> bool:
    """Итог лида из CRM («Сделка заключена»/«Закрыть отказом»).

    С коннектором ERP выигрыш решает бэк-офис (`deal.won`), фронт-офис может только
    отказать до передачи. Без коннектора — как прежде, оба итога.
    """
    if mode == BackofficeMode.LOCAL:
        return True
    return outcome == "lost"
