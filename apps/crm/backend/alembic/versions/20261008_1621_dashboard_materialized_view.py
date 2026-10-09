"""Дашборд: материализованное представление дневной статистики (Фаза 5)

Revision ID: 0006_dashboard
Revises: 0005_auth
Create Date: 2026-10-08 16:30:00+00:00

Обновляется задачей `refresh_dashboard` (CONCURRENTLY, нужен уникальный индекс).
Дни — по часовому поясу Asia/Tashkent. Стоимость моделей — `cost_usd` из
`qualifier_runs` и `messages.meta` (заголовок LiteLLM), а не из Langfuse API.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_dashboard"
down_revision: str | Sequence[str] | None = "0005_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = "Asia/Tashkent"

VIEW = f"""
CREATE MATERIALIZED VIEW mv_daily_stats AS
WITH days AS (
    SELECT generate_series(
        (now() AT TIME ZONE '{TZ}')::date - 179, (now() AT TIME ZONE '{TZ}')::date, interval '1 day'
    )::date AS day
),
leads_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, count(*) AS n FROM leads GROUP BY 1
),
esc_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) AS n,
           count(taken_at) AS taken,
           avg(extract(epoch FROM (taken_at - created_at)) / 60) AS take_min
    FROM escalations GROUP BY 1
),
won_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) FILTER (WHERE to_stage = 'won') AS won,
           count(*) FILTER (WHERE to_stage = 'lost') AS lost
    FROM stage_transitions GROUP BY 1
),
bot_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) FILTER (WHERE meta->>'action' = 'answer') AS answers,
           count(*) FILTER (WHERE meta->>'action' = 'fallback') AS fallbacks,
           coalesce(sum((meta->>'cost_usd')::double precision), 0) AS cost
    FROM messages WHERE role = 'bot' GROUP BY 1
),
qual_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, coalesce(sum(cost_usd), 0) AS cost
    FROM qualifier_runs GROUP BY 1
)
SELECT d.day,
       coalesce(l.n, 0)::int AS leads_created,
       coalesce(e.n, 0)::int AS escalations,
       coalesce(e.taken, 0)::int AS taken,
       coalesce(w.won, 0)::int AS won,
       coalesce(w.lost, 0)::int AS lost,
       coalesce(b.answers, 0)::int AS bot_answers,
       coalesce(b.fallbacks, 0)::int AS fallbacks,
       e.take_min AS avg_take_minutes,
       (coalesce(b.cost, 0) + coalesce(q.cost, 0))::double precision AS cost_usd,
       now() AS refreshed_at
FROM days d
LEFT JOIN leads_d l USING (day)
LEFT JOIN esc_d e USING (day)
LEFT JOIN won_d w USING (day)
LEFT JOIN bot_d b USING (day)
LEFT JOIN qual_d q USING (day)
"""

REASONS = f"""
CREATE MATERIALIZED VIEW mv_escalation_reasons AS
SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, code, count(*)::int AS n
FROM escalations, unnest(reason_codes) AS code
GROUP BY 1, 2
"""


def upgrade() -> None:
    op.execute(VIEW)
    op.execute("CREATE UNIQUE INDEX uq_mv_daily_stats_day ON mv_daily_stats (day)")
    op.execute(REASONS)
    op.execute("CREATE UNIQUE INDEX uq_mv_escalation_reasons ON mv_escalation_reasons (day, code)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_escalation_reasons")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_stats")
