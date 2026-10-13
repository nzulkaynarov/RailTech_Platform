"""Песочница бота «Проверить бота» (аудит 2026-10-12 §3 п. 10): чистые правила без I/O.

Песочница — обычный лид с `source='sandbox'`, привязанный к админу через служебную
Telegram-идентичность с отрицательным id (настоящие id Telegram положительные). Такие лиды
не попадают во «Входящие», списки, дашборд, таймеры и ежедневный отчёт.
"""

from typing import Any, Final

SANDBOX_SOURCE: Final = "sandbox"


def sandbox_identity(user_id: int) -> int:
    """Служебный `tg_user_id` песочницы админа: −id пользователя CRM, с Telegram не пересекается."""
    return -abs(user_id)


def decision_of(metas: list[dict[str, Any]], handed_off: bool) -> str:
    """Решение хода: передача менеджеру важнее ответа; без хода агента — `system`."""
    if handed_off:
        return "handoff"
    for meta in metas:
        action = meta.get("action")
        if isinstance(action, str):
            return action
    return "system"


def chunk_ids(metas: list[dict[str, Any]]) -> list[int]:
    """Фрагменты базы знаний, найденные за ход, без повторов, в порядке выдачи."""
    seen: list[int] = []
    for meta in metas:
        for hit in meta.get("kb_hits") or []:
            chunk = hit.get("chunk_id") if isinstance(hit, dict) else None
            if isinstance(chunk, int) and chunk not in seen:
                seen.append(chunk)
    return seen
