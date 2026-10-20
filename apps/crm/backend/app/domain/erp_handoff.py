"""Передача клиента в бэк-офис задачей после коммита (FIX-31, ADR-0022).

Чистые функции без I/O: состояния, коды, ключ идемпотентности. Состояние лежит на клиенте
(`clients.erp_handoff_*`) и показывается менеджеру в карточке: «передаётся» (`pending`),
«передан» (`done`), «ошибка» (`failed` + код причины).
"""

import hashlib
import json
import uuid
from typing import Any, Final, Literal

HandoffStatus = Literal["pending", "done", "failed"]
PENDING: Final[HandoffStatus] = "pending"
DONE: Final[HandoffStatus] = "done"
FAILED: Final[HandoffStatus] = "failed"

# Код ошибки, когда задачу не удалось поставить в очередь (причины ERP — `Reason`).
ENQUEUE_FAILED: Final = "handoff_enqueue_failed"

# Пространство имён ключей передачи: фиксированный UUID, ключ воспроизводим между процессами.
_KEY_NAMESPACE: Final = uuid.UUID("5d0f6c0e-31b5-4c53-9d3e-7f7a1d6a31f1")


def handoff_idempotency_key(crm_client_id: int, body: dict[str, Any]) -> str:
    """Детерминированный `Idempotency-Key`: функция `crm_client_id` и содержимого передачи.

    Повтор после таймаута шлёт то же тело и получает тот же ключ — ERP отдаёт первый ответ.
    Если между попытками тело изменилось (менеджер добавил контакт), ключ другой: ERP не отвечает
    409 `IDEMPOTENCY_CONFLICT`, а находит клиента по `crm_client_id` и возвращает те же
    идентификаторы без дублей. Случайный `uuid4`, как было раньше, давал новый ключ на каждую
    попытку.
    """
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    return str(uuid.uuid5(_KEY_NAMESPACE, f"handoff:{crm_client_id}:{digest}"))
