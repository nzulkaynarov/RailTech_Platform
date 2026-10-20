"""Строка «События из ERP» центра внешних сервисов (FIX-33, ADR-0024).

Источник — `erp_incoming_events`: что ERP прислала и что CRM с этим сделала. Сбой — событие
отклонено (чужая компания у клиента, неизвестный тип, сломанное тело), обработка упала на потолке
попыток (`failed`) или оно «висит» принятым и не обработанным (воркер стоит, очередь не
разбирается; сборщик раз в минуту ставит такие заново). Лечение — не в CRM: расхождение id
клиента или формата правится на стороне ERP/контракта, поэтому подсказка называет, куда смотреть.
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
    rejected: int
    failed: int
    stuck: int
    last_error: str | None = None


def erp_events(f: ErpEventsFacts) -> CheckResult:
    metrics = {"rejected": f.rejected, "failed": f.failed, "stuck": f.stuck}
    if f.rejected or f.failed or f.stuck:
        parts = []
        if f.rejected:
            parts.append(f"отклонено: {f.rejected}")
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
    if f.stuck and not (f.rejected or f.failed):
        return (
            "События приняты, но не обработаны: проверьте, что воркер CRM работает "
            "(задачи очереди `notify`); зависшие ставятся в очередь автоматически"
        )
    return (
        "«company mismatch» — сверьте сопоставление клиента с компанией в ERP; «invalid event "
        "envelope» или неизвестный тип — ERP прислала событие не по контракту, передайте "
        "разработчикам ERP; «Client not found» — клиент удалён в CRM"
    )
