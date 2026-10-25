"""Фоновые задачи шины rt_bus в EDS (docs/architecture/rt-bus.md §7).

Библиотека регистрирует периодические `rt_bus.pump` (раскладка outbox — «ретранслятор» — и доставка, каждые 5 с),
`rt_bus.requeue_stuck_inbox` (зависшие записи inbox, раз в минуту), `rt_bus.log_metrics` и `rt_bus.purge`, а также
задачу `rt_bus.process_inbox` — обработка принятого события (проекция сотрудников). Выполненные задания воркер
удаляет сам (`delete_jobs="successful"`, `python -m app worker`).
"""

from rt_bus.contrib.procrastinate import install

from app.container import get_container
from app.tasks.queue import queue

tasks = install(queue, lambda: get_container().bus)
