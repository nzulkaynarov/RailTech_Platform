"""SQL rt_bus для PostgreSQL — один текст для обоих адаптеров (L9).

Параметры в стиле `:name` (SQLAlchemy `text()`); адаптер Django переводит их в `%(name)s` функцией `pyformat`.
Время — всегда параметр `:now` (часы настраиваются в `BusConfig.clock`), не `now()` базы.
"""

from __future__ import annotations

import re

OUTBOX = "rt_bus_outbox"
DELIVERY = "rt_bus_delivery"
INBOX = "rt_bus_inbox"
STATE = "rt_bus_subscriber_state"

# Статусы доставки и inbox
PENDING, IN_FLIGHT, DELIVERED, DEAD = "pending", "in_flight", "delivered", "dead"
RECEIVED, PROCESSED, FAILED, SKIPPED = "received", "processed", "failed", "skipped"

_PARAM_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def pyformat(sql: str) -> str:
    """`:name` → `%(name)s` (DB-API pyformat, курсор Django/psycopg)."""
    if "%" in sql:
        raise ValueError("SQL must not contain '%'")
    return _PARAM_RE.sub(r"%(\1)s", sql)


INSERT_OUTBOX = f"""
INSERT INTO {OUTBOX} (id, type, source, subject, correlation_id, envelope, created_at, dispatched_at)
VALUES (:id, :type, :source, :subject, :correlation_id, CAST(:envelope AS jsonb), :now, NULL)
"""

CLAIM_OUTBOX = f"""
SELECT id, type, source FROM {OUTBOX}
WHERE dispatched_at IS NULL
ORDER BY created_at, id
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""

INSERT_DELIVERY = f"""
INSERT INTO {DELIVERY} (event_id, event_type, subscriber, status, attempts, next_attempt_at, created_at, updated_at)
VALUES (:event_id, :event_type, :subscriber, '{PENDING}', 0, :now, :now, :now)
ON CONFLICT (event_id, subscriber) DO NOTHING
"""

MARK_DISPATCHED = f"UPDATE {OUTBOX} SET dispatched_at = :now WHERE id = :id"

# Порядок по имени подписчика: пробные слоты берутся в том же порядке, в каком пишутся итоги (нет взаимной блокировки).
PAUSED_STATES = f"""
SELECT subscriber, consecutive_failures, paused_until FROM {STATE} WHERE paused_until IS NOT NULL ORDER BY subscriber
"""

# Пробная доставка после паузы: одна на подписчика; параллельный воркер ждёт блокировку строки и после
# коммита первого видит новую паузу (на время аренды), поэтому пробу не берёт.
TAKE_PROBE_SLOT = f"""
UPDATE {STATE} SET paused_until = :probe_until, updated_at = :now
WHERE subscriber = :subscriber AND paused_until <= :now AND consecutive_failures >= :threshold
RETURNING paused_until
"""

RESTORE_PROBE_SLOT = f"UPDATE {STATE} SET paused_until = :paused_until WHERE subscriber = :subscriber"

CLAIM_DELIVERIES = f"""
SELECT id FROM {DELIVERY}
WHERE ((status = '{PENDING}' AND next_attempt_at <= :now) OR (status = '{IN_FLIGHT}' AND lease_until < :now))
  AND NOT (subscriber = ANY(CAST(:excluded AS varchar[])))
ORDER BY next_attempt_at, id
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""

# Проба идёт по сроку паузы предохранителя, а не по сроку повтора доставки (C1-G-6): берётся готовая доставка, а если
# готовых нет — ближайшая по расписанию (`next_attempt_at` возвращается: неудача такой пробы расписание не двигает).
CLAIM_PROBE = f"""
SELECT id, next_attempt_at FROM {DELIVERY}
WHERE (status = '{PENDING}' OR (status = '{IN_FLIGHT}' AND lease_until < :now))
  AND subscriber = :subscriber
ORDER BY (status = '{PENDING}' AND next_attempt_at > :now), next_attempt_at, id
LIMIT 1
FOR UPDATE SKIP LOCKED
"""

LEASE_DELIVERY = f"""
UPDATE {DELIVERY}
SET status = '{IN_FLIGHT}', lease_until = :lease_until, lease_token = :token, attempts = attempts + 1,
    last_attempt_at = :now, updated_at = :now
WHERE id = :id
RETURNING id, event_id, event_type, subscriber, attempts
"""

SELECT_ENVELOPE = f"SELECT envelope FROM {OUTBOX} WHERE id = :id"

FINISH_DELIVERED = f"""
UPDATE {DELIVERY}
SET status = '{DELIVERED}', delivered_at = :now, next_attempt_at = NULL, lease_until = NULL, lease_token = NULL,
    last_status_code = :status_code, last_error = NULL, updated_at = :now
WHERE id = :id AND lease_token = :token AND status = '{IN_FLIGHT}'
"""

FINISH_RETRY = f"""
UPDATE {DELIVERY}
SET status = '{PENDING}', next_attempt_at = :next_attempt_at, lease_until = NULL, lease_token = NULL,
    last_status_code = :status_code, last_error = :error, updated_at = :now
WHERE id = :id AND lease_token = :token AND status = '{IN_FLIGHT}'
"""

FINISH_POSTPONE = f"""
UPDATE {DELIVERY}
SET status = '{PENDING}', next_attempt_at = :next_attempt_at, lease_until = NULL, lease_token = NULL,
    attempts = GREATEST(attempts - 1, 0), last_error = :error, updated_at = :now
WHERE id = :id AND lease_token = :token AND status = '{IN_FLIGHT}'
"""

FINISH_DEAD = f"""
UPDATE {DELIVERY}
SET status = '{DEAD}', next_attempt_at = NULL, lease_until = NULL, lease_token = NULL,
    last_status_code = :status_code, last_error = :error, updated_at = :now
WHERE id = :id AND lease_token = :token AND status = '{IN_FLIGHT}'
"""

# Успех закрывает предохранитель. Возвращает счётчик ошибок подряд ДО успеха (CTE видит состояние до оператора): если он
# достиг порога, подписчик восстановился и его ожидающие доставки сбрасываются на «сейчас» (RESET_BACKLOG).
BREAKER_SUCCESS = f"""
WITH previous AS (SELECT consecutive_failures FROM {STATE} WHERE subscriber = :subscriber)
INSERT INTO {STATE} (subscriber, consecutive_failures, paused_until, last_success_at, updated_at)
VALUES (:subscriber, 0, NULL, :now, :now)
ON CONFLICT (subscriber) DO UPDATE
SET consecutive_failures = 0, paused_until = NULL, last_success_at = :now, updated_at = :now
RETURNING COALESCE((SELECT consecutive_failures FROM previous), 0) AS previous_failures
"""

# Догон после восстановления подписчика (C1-G-6): ожидающие повторы не ждут расписания, а уходят следующей пачкой.
RESET_BACKLOG = f"""
UPDATE {DELIVERY} SET next_attempt_at = :now, updated_at = :now
WHERE subscriber = :subscriber AND status = '{PENDING}' AND next_attempt_at > :now
"""

BREAKER_FAILURE = f"""
INSERT INTO {STATE} (subscriber, consecutive_failures, paused_until, last_failure_at, last_error, updated_at)
VALUES (:subscriber, 1, CASE WHEN 1 >= :threshold THEN CAST(:pause_until AS timestamptz) END, :now, :error, :now)
ON CONFLICT (subscriber) DO UPDATE
SET consecutive_failures = {STATE}.consecutive_failures + 1,
    paused_until = CASE WHEN {STATE}.consecutive_failures + 1 >= :threshold
                        THEN CAST(:pause_until AS timestamptz) ELSE {STATE}.paused_until END,
    last_failure_at = :now, last_error = :error, updated_at = :now
RETURNING consecutive_failures, paused_until
"""

RETRY_DELIVERY = f"""
UPDATE {DELIVERY}
SET status = '{PENDING}', attempts = 0, next_attempt_at = :now, lease_until = NULL, lease_token = NULL,
    updated_at = :now
WHERE id = :id AND status IN ('{DEAD}', '{PENDING}')
RETURNING id, subscriber
"""

RETRY_ALL_DEAD = f"""
UPDATE {DELIVERY}
SET status = '{PENDING}', attempts = 0, next_attempt_at = :now, lease_until = NULL, lease_token = NULL,
    updated_at = :now
WHERE status = '{DEAD}' AND (CAST(:subscriber AS varchar) IS NULL OR subscriber = CAST(:subscriber AS varchar))
RETURNING id, subscriber
"""

# Ручной повтор: подписчик на паузе предохранителя сразу получает одну пробную доставку (не ждёт конца паузы).
PROBE_NOW = f"""
UPDATE {STATE} SET paused_until = :now, updated_at = :now
WHERE subscriber = ANY(CAST(:subscribers AS varchar[])) AND paused_until > :now
"""

LIST_DELIVERIES = f"""
SELECT d.id, d.event_id, d.event_type, d.subscriber, d.status, d.attempts, d.next_attempt_at,
       d.last_attempt_at, d.last_status_code, d.last_error, d.delivered_at, d.created_at,
       o.subject, o.correlation_id, o.created_at AS event_created_at
FROM {DELIVERY} d LEFT JOIN {OUTBOX} o ON o.id = d.event_id
WHERE (CAST(:status AS varchar) IS NULL OR d.status = CAST(:status AS varchar))
  AND (CAST(:subscriber AS varchar) IS NULL OR d.subscriber = CAST(:subscriber AS varchar))
  AND (CAST(:event_type AS varchar) IS NULL OR d.event_type = CAST(:event_type AS varchar))
  AND (CAST(:event_id AS uuid) IS NULL OR d.event_id = CAST(:event_id AS uuid))
  AND (CAST(:before_id AS bigint) IS NULL OR d.id < CAST(:before_id AS bigint))
ORDER BY d.id DESC
LIMIT :limit
"""

INSERT_INBOX = f"""
INSERT INTO {INBOX} (event_id, type, source, publisher, subject, correlation_id, envelope, status, attempts, error,
                     received_at, processed_at, updated_at)
VALUES (:event_id, :type, :source, :publisher, :subject, :correlation_id, CAST(:envelope AS jsonb), :status, 0,
        :error, :now, CAST(:processed_at AS timestamptz), :now)
ON CONFLICT (event_id) DO NOTHING
RETURNING event_id
"""

LOCK_INBOX = f"""
SELECT event_id, type, envelope, status, next_attempt_at FROM {INBOX}
WHERE event_id = :event_id FOR UPDATE SKIP LOCKED
"""

FINISH_INBOX = f"""
UPDATE {INBOX} SET status = :status, attempts = attempts + 1, error = :error, processed_at = :now,
    next_attempt_at = NULL, updated_at = :now
WHERE event_id = :event_id
"""

# Ошибка обработчика: счётчик и текст; дальше — повтор позже (INBOX_RETRY_LATER) или failed (INBOX_FAILED).
INBOX_FAILURE = f"""
UPDATE {INBOX} SET attempts = attempts + 1, error = :error, updated_at = :now
WHERE event_id = :event_id AND status = '{RECEIVED}'
RETURNING attempts
"""

INBOX_RETRY_LATER = f"UPDATE {INBOX} SET next_attempt_at = :next_attempt_at WHERE event_id = :event_id"

INBOX_FAILED = f"UPDATE {INBOX} SET status = '{FAILED}', next_attempt_at = NULL WHERE event_id = :event_id"

RETRY_INBOX = f"""
UPDATE {INBOX} SET status = '{RECEIVED}', attempts = 0, error = NULL, processed_at = NULL, next_attempt_at = NULL,
    updated_at = :now
WHERE event_id = :event_id AND status IN ('{FAILED}', '{SKIPPED}')
RETURNING event_id
"""

# Подбор: `received`, не взятые очередью дольше `before`, и повторы, чей срок настал. Отметка updated_at (и сброс
# next_attempt_at) — следующий подбор не ставит ту же запись снова, пока очередь её не обработала.
STUCK_INBOX = f"""
UPDATE {INBOX} SET updated_at = :now, next_attempt_at = NULL
WHERE event_id IN (
    SELECT event_id FROM {INBOX}
    WHERE status = '{RECEIVED}'
      AND ((next_attempt_at IS NULL AND updated_at < :before) OR next_attempt_at <= :now)
    ORDER BY received_at
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
)
RETURNING event_id
"""

LIST_INBOX = f"""
SELECT event_id, type, source, publisher, subject, correlation_id, status, attempts, error, received_at,
       processed_at
FROM {INBOX}
WHERE (CAST(:status AS varchar) IS NULL OR status = CAST(:status AS varchar))
  AND (CAST(:event_type AS varchar) IS NULL OR type = CAST(:event_type AS varchar))
  AND (CAST(:before AS timestamptz) IS NULL OR received_at < CAST(:before AS timestamptz))
ORDER BY received_at DESC, event_id
LIMIT :limit
"""

METRICS_OUTBOX = f"SELECT count(*) AS pending, min(created_at) AS oldest FROM {OUTBOX} WHERE dispatched_at IS NULL"

METRICS_DELIVERY = f"""
SELECT d.subscriber, d.status, count(*) AS n, min(o.created_at) AS oldest
FROM {DELIVERY} d LEFT JOIN {OUTBOX} o ON o.id = d.event_id
WHERE d.status IN ('{PENDING}', '{IN_FLIGHT}', '{DEAD}')
GROUP BY d.subscriber, d.status
"""

METRICS_STATE = f"SELECT subscriber, consecutive_failures, paused_until FROM {STATE}"

METRICS_INBOX = f"""
SELECT status, count(*) AS n, count(next_attempt_at) AS retrying, min(received_at) AS oldest FROM {INBOX}
WHERE status IN ('{RECEIVED}', '{FAILED}') GROUP BY status
"""

PURGE_DELIVERIES = f"DELETE FROM {DELIVERY} WHERE status = '{DELIVERED}' AND delivered_at < :before"
PURGE_OUTBOX = f"""
DELETE FROM {OUTBOX} o WHERE o.dispatched_at < :before
  AND NOT EXISTS (SELECT 1 FROM {DELIVERY} d WHERE d.event_id = o.id)
"""
PURGE_INBOX = f"""
DELETE FROM {INBOX} WHERE status IN ('{PROCESSED}', '{SKIPPED}') AND processed_at < :before
"""
