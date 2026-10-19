"""Проверка «Синхронизация с ERP» центра внешних сервисов (FIX-11, ADR-0024).

Источник — `users.erp_sync_error`: задачи `erp_provision_user` и `erp_revoke_sessions` пишут туда
итог каждой попытки (ошибка — до первого успеха). Временные сбои и «коннектор не настроен» задача
повторяет сама (`tasks/erp_users.RETRY`, несколько минут); постоянные (e-mail занят) — нет.
Админ видит сбой здесь, а не в ответе на «Доступ к ERP»: пользователь ждёт, что учётная запись
появится, а ошибка ERP — задача админа.
"""

from dataclasses import dataclass

from app.domain.external_status import CheckResult

KEY = "erp_sync"
ERP_TAB = "«Подключения» → «ERP»"
_REGRANT = "снимите и снова выдайте доступ"


@dataclass(frozen=True, slots=True)
class ErpSyncFacts:
    configured: bool
    with_access: int  # сколько активных сотрудников с `erp` в `platform_access`
    failed: int  # у скольких последняя попытка синхронизации закончилась ошибкой
    last_error: str | None = None


def erp_sync(f: ErpSyncFacts) -> CheckResult:
    metrics = {"with_access": f.with_access, "failed": f.failed}
    if f.failed:
        return CheckResult(
            KEY,
            "fail",
            f"Доступ к ERP не синхронизирован у сотрудников: {f.failed}",
            error=f.last_error,
            hint=_hint(f),
            metrics=metrics,
        )
    if not f.configured and not f.with_access:
        return CheckResult(
            KEY,
            "off",
            "ERP не подключена — выдавать доступ к ней пока некому",
            hint=f"Подключите ERP: {ERP_TAB}",
            metrics=metrics,
        )
    if not f.with_access:
        return CheckResult(KEY, "ok", "Доступ к ERP пока никому не выдан", metrics=metrics)
    return CheckResult(
        KEY, "ok", f"Доступ к ERP синхронизирован: сотрудников — {f.with_access}", metrics=metrics
    )


def _hint(f: ErpSyncFacts) -> str:
    if not f.configured:
        return (
            f"ERP не подключена: укажите адрес и сервисный токен в {ERP_TAB} — задача повторяется "
            f"сама в течение нескольких минут; если попытки кончились, {_REGRANT}"
        )
    return (
        f"Проверьте связь с ERP в {ERP_TAB}. Временные сбои задача повторяет сама в течение "
        f"нескольких минут; если попытки кончились, {_REGRANT}. Если e-mail занят пользователем "
        "ERP, исправьте его в ERP и снова выдайте доступ"
    )
