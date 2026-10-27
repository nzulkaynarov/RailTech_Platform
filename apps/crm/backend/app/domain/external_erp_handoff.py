"""Строка «Передача клиентов в ERP» центра внешних сервисов (FIX-31, ADR-0024).

Источник — `clients.erp_handoff_*`: задача `erp_handoff_client` пишет туда итог каждой попытки.
Сбой — клиенты, у которых передача закончилась ошибкой (постоянной: 409 ИНН, нет согласия; или
временной после последней попытки), и те, кто «передаётся» слишком долго (воркер стоит или очередь
не разбирается). Временные сбои задача повторяет сама; постоянные менеджер исправляет в карточке
клиента и повторяет передачу.
"""

from dataclasses import dataclass

from app.domain.external_status import CheckResult

KEY = "erp_handoff"
ERP_TAB = "«Подключения» → «ERP»"
# Дольше этого «передаётся» считается зависшей: задача повторяется ≤ 6 раз с паузами до 30 с × n.
STUCK_AFTER_MINUTES = 30


@dataclass(frozen=True, slots=True)
class ErpHandoffFacts:
    configured: bool
    failed: int  # клиентов с ошибкой передачи
    stuck: int  # «передаётся» дольше `STUCK_AFTER_MINUTES`
    pending: int  # «передаётся» сейчас, включая свежие
    last_error: str | None = None


def erp_handoff(f: ErpHandoffFacts) -> CheckResult:
    metrics = {"failed": f.failed, "stuck": f.stuck, "pending": f.pending}
    if f.failed or f.stuck:
        parts = []
        if f.failed:
            parts.append(f"с ошибкой: {f.failed}")
        if f.stuck:
            parts.append(f"зависли в очереди: {f.stuck}")
        return CheckResult(
            KEY,
            "fail",
            f"Клиенты не переданы в ERP — {', '.join(parts)}",
            error=f.last_error,
            hint=_hint(f),
            metrics=metrics,
            cause="erp_not_connected" if not f.configured else "erp_handoff_failed",
        )
    if not f.configured and not f.pending:
        return CheckResult(
            KEY,
            "off",
            "ERP не подключена — передавать клиентов пока некуда",
            hint=f"Подключите ERP: {ERP_TAB}",
            metrics=metrics,
            cause="erp_not_connected",
        )
    return CheckResult(KEY, "ok", "Клиенты передаются в ERP без ошибок", metrics=metrics)


def _hint(f: ErpHandoffFacts) -> str:
    if f.stuck and not f.failed:
        return (
            "Передача стоит в очереди: проверьте, что воркер CRM работает, и связь с ERP в "
            f"{ERP_TAB}. Потом откройте клиента и повторите передачу"
        )
    return (
        "Откройте клиента с ошибкой: код причины и что делать — в его карточке. ИНН уже есть у "
        "другого клиента в ERP — исправьте ИНН; нет согласия — оформите его у лида; ERP недоступна "
        f"— проверьте связь в {ERP_TAB}. Затем нажмите «Повторить передачу»"
    )
