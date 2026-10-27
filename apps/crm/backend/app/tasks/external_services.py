"""Фоновые проверки центра внешних сервисов (M3-CRM-12, ADR-0024).

Дешёвые — раз в минуту (health, журнал шлюза за 15 мин, журнал писем); тяжёлые — раз в 15 мин
(SMTP-соединение без отправки, место в бакетах, сутки журнала шлюза, TLS) и чистка старых проверок.
Сломанное перепроверяется с затуханием (1, 2, 5, 15 мин, дальше раз в 15): дешёвые сервисы
минутный проход пропускает, пока не подошёл срок, а сервисы только тяжёлого уровня (сертификаты) —
`external_checks_recheck`. Восстановившееся снимается само, оповещения — по причине (W15-H3).
"""

from datetime import UTC, datetime

from app.container import get_container
from app.tasks.queue import queue


@queue.periodic(cron="* * * * *", periodic_id="external_checks_cheap")
@queue.task(name="external_checks_cheap", queue="timers", queueing_lock="external_checks_cheap")
async def external_checks_cheap(timestamp: int) -> int:
    results = await get_container().external_checks.run(
        "cheap", datetime.fromtimestamp(timestamp, UTC)
    )
    return len(results)


@queue.periodic(cron="*/15 * * * *", periodic_id="external_checks_heavy")
@queue.task(name="external_checks_heavy", queue="timers", queueing_lock="external_checks_heavy")
async def external_checks_heavy(timestamp: int) -> int:
    results = await get_container().external_checks.run(
        "heavy", datetime.fromtimestamp(timestamp, UTC)
    )
    return len(results)


@queue.periodic(cron="* * * * *", periodic_id="external_checks_recheck")
@queue.task(name="external_checks_recheck", queue="timers", queueing_lock="external_checks_recheck")
async def external_checks_recheck(timestamp: int) -> int:
    results = await get_container().external_checks.recheck_broken(
        datetime.fromtimestamp(timestamp, UTC)
    )
    return len(results)
