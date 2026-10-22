"""Строка «События из ERP» центра внешних сервисов (FIX-33, ADR-0024).

Источник — таблицы шины rt_bus (B4, CONTRACTS §9): inbox (что ERP прислала и что CRM с этим
сделала) и доставки (что CRM отправила подписчикам). Сбой — обработка упала на потолке попыток
(`failed`: чужая компания у клиента, клиента нет, обработчик упал), событие «висит» принятым и не
обработанным (воркер стоит, очередь не разбирается; сборщик раз в минуту ставит такие заново) или
событие CRM не доставлено подписчику (`dead`, DLQ). Лечение — не в CRM: расхождение id клиента или
формата правится на стороне ERP/контракта, недоставленное повторяют из журнала шины (runbook
`rt-bus-crm.md`); подсказка называет, куда смотреть.
"""

from dataclasses import dataclass

from app.domain.external_status import CheckResult

KEY = "erp_events"
# Принято, но не обработано дольше этого — зависло (сборщик и воркер должны были успеть).
STUCK_AFTER_MINUTES = 10
# События старше этого срока в счётчиках не участвуют: старое расхождение не должно гореть вечно.
WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class ErpEventsFacts:
    dead: int
    failed: int
    stuck: int
    last_error: str | None = None


def erp_events(f: ErpEventsFacts) -> CheckResult:
    metrics = {"dead": f.dead, "failed": f.failed, "stuck": f.stuck}
    if f.dead or f.failed or f.stuck:
        parts = []
        if f.dead:
            parts.append(f"не доставлено ERP: {f.dead}")
        if f.failed:
            parts.append(f"не обработано: {f.failed}")
        if f.stuck:
            parts.append(f"зависло: {f.stuck}")
        return CheckResult(
            KEY,
            "fail",
            f"События из ERP за {WINDOW_DAYS} дн. — {', '.join(parts)}",
            error=f.last_error,
            hint=_hint(f),
            metrics=metrics,
        )
    return CheckResult(KEY, "ok", "События из ERP принимаются без ошибок", metrics=metrics)


def _hint(f: ErpEventsFacts) -> str:
    if f.stuck and not (f.dead or f.failed):
        return (
            "События приняты, но не обработаны: проверьте, что воркер CRM работает "
            "(очередь `rt_bus`, задача `rt_bus.process_inbox`); зависшие ставятся в очередь "
            "автоматически"
        )
    return (
        "«company mismatch» — сверьте сопоставление клиента с компанией в ERP; «Client not found» "
        "— клиент удалён в CRM; недоставленное ERP — проверьте адрес и секрет шины и повторите "
        "доставку из журнала (runbook rt-bus-crm)"
    )
