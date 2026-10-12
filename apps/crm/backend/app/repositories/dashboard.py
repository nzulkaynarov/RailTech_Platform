"""Агрегаты дашборда по менеджерам и SLA (SPEC §10.1).

Живые запросы, а не материализованное представление: медиана за произвольный период не
складывается из дневных строк, а передач — единицы-сотни в месяц (индексы по `escalations`
хватает). Лиды песочницы «Проверить бота» (`source = 'sandbox'`) не считаются.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Один вид фильтра песочницы во всех запросах (его проверяет tests/unit/services/test_sandbox.py).
_REAL_LEAD = "lead_id IN (SELECT leads.id FROM leads WHERE leads.source != 'sandbox')"

TAKEN = text(
    f"""
    SELECT taken_by_user_id AS user_id,
           count(*) AS taken,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM (taken_at - created_at)) / 60
           ) AS median_min
    FROM escalations
    WHERE taken_at >= :since AND taken_by_user_id IS NOT NULL AND {_REAL_LEAD}
    GROUP BY taken_by_user_id
    """  # noqa: S608 — константа модуля, без пользовательского ввода
)
WON = text(
    f"""
    SELECT owner_user_id AS user_id, count(*) AS won
    FROM deals
    WHERE stage = 'won' AND closed_at >= :since AND owner_user_id IS NOT NULL
      AND (lead_id IS NULL OR {_REAL_LEAD})
    GROUP BY owner_user_id
    """  # noqa: S608 — константа модуля, без пользовательского ввода
)
ACTIVE = text(
    """
    SELECT assigned_user_id AS user_id, count(*) AS active
    FROM leads
    WHERE assigned_user_id IS NOT NULL AND erased_at IS NULL AND leads.source != 'sandbox'
      AND stage NOT IN ('won', 'customer', 'lost')
    GROUP BY assigned_user_id
    """
)
NAMES = text("SELECT id, full_name FROM users WHERE id = ANY(:ids)")
# Срок SLA «решён»: передачу забрали или срок уже прошёл. Открытая передача с будущим
# сроком в знаменатель не входит — она ещё может уложиться.
SLA = text(
    f"""
    SELECT count(*) FILTER (WHERE taken_at IS NOT NULL OR sla_due_at < :now) AS due,
           count(*) FILTER (WHERE taken_at IS NOT NULL AND taken_at <= sla_due_at) AS met
    FROM escalations
    WHERE created_at >= :since AND sla_due_at IS NOT NULL AND {_REAL_LEAD}
    """  # noqa: S608 — константа модуля, без пользовательского ввода
)


async def manager_rows(session: AsyncSession, since: datetime) -> dict[str, list[Any]]:
    """Три среза по пользователю (забрал, выиграл, ведёт) и имена; склейка — в сервисе."""
    params = {"since": since}
    taken = (await session.execute(TAKEN, params)).mappings().all()
    won = (await session.execute(WON, params)).mappings().all()
    active = (await session.execute(ACTIVE)).mappings().all()
    ids = sorted({int(r["user_id"]) for r in [*taken, *won, *active]})
    names = (await session.execute(NAMES, {"ids": ids})).mappings().all() if ids else []
    return {"taken": list(taken), "won": list(won), "active": list(active), "names": list(names)}


async def sla_counts(session: AsyncSession, since: datetime, now: datetime) -> tuple[int, int]:
    """(передач с решённым сроком SLA, из них забраны в срок)."""
    rows = (await session.execute(SLA, {"since": since, "now": now})).mappings().all()
    if not rows:
        return 0, 0
    return int(rows[0]["due"] or 0), int(rows[0]["met"] or 0)
