"""Запасной путь B-073 (D2-1): провижининг прав ERP заново всем активным сотрудникам с ERP.

    python -m app reprovision-erp

Обычно не нужен: воркер при старте сам ставит провижининг, когда меняется ERP-часть каталога
`platform-rbac.yaml` (`services/identity_catalog.py`). Безопасно повторять: ERP перезаписывает роль
«CRM Sync» вычисленным набором прав.
"""

import sys

from app.container import get_container
from app.services.identity_catalog import reprovision_erp_users
from app.tasks.erp_users import enqueue_erp_sync


async def run() -> int:
    from app.tasks.queue import queue

    container = get_container()
    try:
        async with queue.open_async():
            count = await reprovision_erp_users(container.session_factory, enqueue_erp_sync)
    finally:
        await container.aclose()
    sys.stdout.write(f"Поставлено задач провижининга ERP: {count}.\n")
    return 0
