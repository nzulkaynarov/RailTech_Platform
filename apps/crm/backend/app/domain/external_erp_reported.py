"""Внешние сервисы ERP в центре внешних сервисов CRM (M3-ERP-06, ADR-0024).

`Health.externals[]` → результат проверки. CRM сама эти сервисы не проверяет: состояние по
журналам и счётчикам передаёт ERP в ответе `GET /health` (кэш коннектора 30 с, запросов нет).
Чистые функции, без ввода-вывода.

Правила: ERP не подключена — `off`; ERP не отвечает — `unknown` (сбой самой ERP виден в «Состоянии
системы» и строке «Подключения → ERP», шесть дублирующих инцидентов не нужны); ERP старше M3-ERP-06
(нет поля) — `unknown`; неизвестный `code` и `status` читатель терпит (Q-FIX35-4).
`degraded` → `warn`; `fail` → `fail` (только он открывает инцидент и оповещение, как у остальных
сервисов); `disabled` → `off`.
"""

from typing import Final

from app.domain.external_registry import ERP_REPORTED_REASON, ERP_SERVICE_PREFIX, Status
from app.domain.external_status import CheckResult, Metric
from app.domain.system_status import ErpExternal, ErpFacts

ERP_TAB: Final = "«Подключения» → «ERP»"
SERVER_HINT: Final = "Настройка сервиса — в окружении ERP: обратитесь к администратору сервера"
_STATUS: Final[dict[str, Status]] = {
    "ok": "ok",
    "degraded": "warn",
    "fail": "fail",
    "unknown": "unknown",
    "disabled": "off",
}

#: Что случилось (ok / сбой / давно не было успеха) и что сделать — по коду сервиса ERP.
_TEXT: Final[dict[str, dict[str, str]]] = {
    "cbu_rates": {
        "ok": "Курсы ЦБ загружаются",
        "fail": "ERP не загружает курсы ЦБ — КП в иностранной валюте могут остановиться",
        "hint": "Проверьте, что ERP достаёт cbu.uz; без курса финансист задаёт курс КП вручную",
        "off_unconfigured": "Загрузка курсов ЦБ не настроена",
    },
    "customs_tariff": {
        "ok": "Справочник ТН ВЭД синхронизируется",
        "fail": "ERP не синхронизирует справочник ТН ВЭД — коды в карточках не обновляются",
        "hint": "Проверьте, что ERP достаёт tarif.customs.uz; прежний справочник остаётся",
        "off_unconfigured": "Синхронизация ТН ВЭД не настроена",
    },
    "mail": {
        "ok": "Почта ERP отправляет письма",
        "fail": "ERP не может отправить письма — клиенты не получают приглашения и КП",
        "hint": "Проверьте почтовый релей ERP (адрес, логин, пароль); письма — в журнале ERP",
        "off_unconfigured": "Почтовый релей ERP не настроен — письма клиентам не уходят",
    },
    "litellm": {
        "ok": "ERP получает ответы моделей через шлюз",
        "fail": "ERP не получает ответы моделей — разбор запросов и черновики КП недоступны",
        "hint": "Проверьте шлюз и ключ ERP в «Модели ИИ»; работа с КП вручную продолжается",
        "off_unconfigured": "ИИ в ERP не настроен (выключен или нет ключа шлюза)",
    },
    "s3": {
        "ok": "ERP читает и пишет файлы в хранилище",
        "fail": "ERP не может читать и писать файлы — PDF и вложения недоступны",
        "hint": "Проверьте хранилище (RustFS) и ключи доступа ERP",
        "off_unconfigured": "Файловое хранилище ERP не настроено — файлы лежат на диске сервера",
    },
    "sentry": {
        "ok": "Сбор ошибок ERP подключён",
        "fail": "Сбор ошибок ERP не работает",
        "hint": SERVER_HINT,
        "off_unconfigured": "Сбор ошибок ERP (Sentry) не настроен — необязательно",
    },
}
_FALLBACK_TEXT: Final = {
    "ok": "Работает",
    "fail": "Сервис ERP не работает",
    "hint": "Посмотрите журнал ERP",
    "off_unconfigured": "Не настроен в ERP",
}


def erp_code(key: str) -> str:
    return key.removeprefix(ERP_SERVICE_PREFIX)


def _metrics(item: ErpExternal) -> dict[str, Metric]:
    return {
        "ok_24h": item.ok_24h,
        "errors_24h": item.errors_24h,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
        "last_error_at": item.last_error_at.isoformat() if item.last_error_at else None,
    }


def erp_external(key: str, erp: ErpFacts) -> CheckResult:
    """Результат проверки сервиса ERP `key` (`erp.<code>`) по последнему ответу `GET /health`."""
    if not erp.configured:
        return CheckResult(
            key,
            "off",
            "ERP не подключена — состояние её внешних сервисов не собирается",
            hint=f"Подключите ERP: {ERP_TAB}",
        )
    if erp.error is not None:
        return CheckResult(
            key,
            "unknown",
            "ERP не отвечает — состояние её внешних сервисов неизвестно",
            error=erp.error,
            hint=f"Сначала восстановите связь с ERP: {ERP_TAB} → «Проверить связь»",
        )
    if erp.externals is None:
        return CheckResult(
            key,
            "unknown",
            ERP_REPORTED_REASON,
            hint="Обновите ERP до версии с M3-ERP-06: она передаёт состояние внешних сервисов",
        )
    code = erp_code(key)
    item = next((e for e in erp.externals if e.code == code), None)
    if item is None:
        return CheckResult(key, "unknown", "ERP не передала состояние этого сервиса")
    return _result(key, code, item)


def _result(key: str, code: str, item: ErpExternal) -> CheckResult:
    text = _TEXT.get(code, _FALLBACK_TEXT)
    status = _STATUS.get(item.status, "unknown")
    metrics = _metrics(item)
    if status == "off":
        summary = (
            "Выключен из CRM — ERP не обращается к сервису"
            if not item.enabled
            else text["off_unconfigured"]
        )
        hint = None if not item.enabled else SERVER_HINT
        return CheckResult(key, "off", summary, hint=hint, metrics=metrics)
    if status == "ok":
        return CheckResult(key, "ok", text["ok"], metrics=metrics)
    if status == "unknown":
        return CheckResult(
            key, "unknown", "Данных пока нет — сервис ещё не использовался", metrics=metrics
        )
    failing = item.last_error_at is not None and (
        item.last_success_at is None or item.last_error_at > item.last_success_at
    )
    if status == "fail":
        summary = text["fail"]
    elif failing:
        summary = f"Последняя операция не удалась, до этого работало: {text['ok'].lower()}"
    else:
        summary = "Давно не было успешной операции — проверьте плановые задачи ERP"
    return CheckResult(
        key, status, summary, error=item.last_error, hint=text["hint"], metrics=metrics
    )
