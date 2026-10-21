"""FIX-67b — in-flight-блокировка «Разобрать текст (ИИ)» по КП.

Фронтенд блокирует кнопку на время запроса, но двойной клик, повтор сети и две вкладки доходят до сервера. Пока
разбор КП идёт, второй запрос не ставит новую (платную) задачу и не пишет строки. Ключ — в общем Redis-кэше ERP,
захват атомарный (`cache.add`), как в take-and-prepare (`draft_quote_inflight`), но по КП, а не по паре
сделка+пользователь: дубли строк возникают в КП, кто бы ни нажал.

Значение ключа: `pending:<user_id>` (задача ещё публикуется) → `<task_id>:<user_id>` (задача в очереди).
Блокировку снимает: воркер в `finally` обработчика (успех или ошибка), вьюха при неудачной постановке,
следующий запрос — если результат задачи уже лежит в backend (задача упала молча), иначе — TTL.
"""

from typing import Optional

from django.core.cache import cache

# Жёсткий лимит задачи `run_ai_job` — 600 с (+ ожидание в очереди): блокировка живёт дольше, чтобы не истечь
# под ещё работающей задачей и не пустить вторую.
LOCK_TTL_SECONDS = 900
_PENDING = "pending"


def lock_key(quote_id: int) -> str:
    return f"parse_request_text_inflight:{quote_id}"


def acquire(quote_id: int, user_id: int) -> bool:
    """Атомарно занять блокировку КП. False — разбор этого КП уже идёт."""
    return bool(cache.add(lock_key(quote_id), f"{_PENDING}:{user_id}", timeout=LOCK_TTL_SECONDS))


def attach_task(quote_id: int, user_id: int, task_id: str) -> None:
    """Записать id поставленной задачи в блокировку (чтобы повтор того же пользователя получил тот же job).

    Пишем только в СВОЙ ещё «pending» лок: снятый (TTL/перехват) не воскрешаем, чужой новый не затираем. Быстрая
    задача (`AI_DISABLED`, `QUOTE_NOT_FOUND`) могла завершиться раньше этого вызова — её `release` не узнал лок
    (task_id в нём ещё не было), поэтому уже завершённому job лок не ставим, а снимаем."""
    key = lock_key(quote_id)
    if cache.get(key) != f"{_PENDING}:{user_id}":
        return
    if job_is_finished(task_id):
        cache.delete(key)
        return
    cache.set(key, f"{task_id}:{user_id}", timeout=LOCK_TTL_SECONDS)


def holder(quote_id: int) -> Optional[tuple]:
    """(task_id | None, user_id | None) текущего держателя блокировки или None, если её нет."""
    raw = cache.get(lock_key(quote_id))
    if not raw:
        return None
    task_id, _, user_id = str(raw).rpartition(":")
    return (None if task_id == _PENDING else task_id), (int(user_id) if user_id.isdigit() else None)


def release(quote_id: int, job_id: Optional[str] = None) -> None:
    """Снять блокировку. С `job_id` — только если она принадлежит этому job (опоздавшая старая задача не снимает
    блокировку более нового разбора); без `job_id` — безусловно (вьюха после неудачной постановки)."""
    key = lock_key(quote_id)
    if job_id is not None:
        raw = cache.get(key)
        if not raw or not str(raw).startswith(f"{job_id}:"):
            return
    cache.delete(key)


def job_is_finished(task_id: str) -> bool:
    """Результат задачи уже в backend (успех/ошибка/падение воркера) — блокировка устарела. Любой сбой backend —
    «не знаю», то есть блокировка остаётся до TTL."""
    try:
        from celery.result import AsyncResult

        return bool(AsyncResult(task_id).ready())
    except Exception:  # noqa: BLE001 — недоступный backend не должен ломать кнопку
        return False
