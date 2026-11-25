"""partner_not_lost_sale: a partner hand-over is not a lost sale on the dashboard (ЛП-1)

Such a lead is closed with stage `lost` (`stage_transitions.reason = 'handed over as a partner'`),
but it is not a lost sale: `mv_daily_stats.lost` does not count those transitions. Both views are
recreated with the same columns and unique indexes (needed by REFRESH CONCURRENTLY). Downgrade
restores the definition without the exclusion.

Revision ID: 520841a91c2e
Revises: 331d20a4cab7
Create Date: 2026-11-25 07:08:46.445494+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "520841a91c2e"
down_revision: str | Sequence[str] | None = "331d20a4cab7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = "Asia/Tashkent"
REAL = "lead_id NOT IN (SELECT id FROM leads WHERE source = 'sandbox')"


def _view(skip_partner: bool) -> str:
    not_partner = " AND reason IS DISTINCT FROM 'handed over as a partner'" if skip_partner else ""
    lead_where = "WHERE source <> 'sandbox'"
    by_lead = f"WHERE {REAL}"
    msg_where = f"AND conversation_id IN (SELECT id FROM conversations WHERE {REAL})"
    return f"""
CREATE MATERIALIZED VIEW mv_daily_stats AS
WITH days AS (
    SELECT generate_series(
        (now() AT TIME ZONE '{TZ}')::date - 179, (now() AT TIME ZONE '{TZ}')::date, interval '1 day'
    )::date AS day
),
leads_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, count(*) AS n FROM leads {lead_where}
    GROUP BY 1
),
esc_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) AS n,
           count(taken_at) AS taken,
           avg(extract(epoch FROM (taken_at - created_at)) / 60) AS take_min
    FROM escalations {by_lead} GROUP BY 1
),
won_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) FILTER (WHERE to_stage = 'won') AS won,
           count(*) FILTER (WHERE to_stage = 'lost'{not_partner}) AS lost
    FROM stage_transitions {by_lead} GROUP BY 1
),
bot_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day,
           count(*) FILTER (WHERE meta->>'action' = 'answer') AS answers,
           count(*) FILTER (WHERE meta->>'action' = 'fallback') AS fallbacks,
           coalesce(sum((meta->>'cost_usd')::double precision), 0) AS cost
    FROM messages WHERE role = 'bot' {msg_where} GROUP BY 1
),
qual_d AS (
    SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, coalesce(sum(cost_usd), 0) AS cost
    FROM qualifier_runs {by_lead} GROUP BY 1
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


def _reasons() -> str:
    where = f"WHERE {REAL}" if True else ""
    return f"""
CREATE MATERIALIZED VIEW mv_escalation_reasons AS
SELECT (created_at AT TIME ZONE '{TZ}')::date AS day, code, count(*)::int AS n
FROM escalations, unnest(reason_codes) AS code
{where}
GROUP BY 1, 2
"""


def _recreate(skip_partner: bool) -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_escalation_reasons")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_stats")
    op.execute(_view(skip_partner))
    op.execute("CREATE UNIQUE INDEX uq_mv_daily_stats_day ON mv_daily_stats (day)")
    op.execute(_reasons())
    op.execute("CREATE UNIQUE INDEX uq_mv_escalation_reasons ON mv_escalation_reasons (day, code)")


def upgrade() -> None:
    _recreate(skip_partner=True)


def downgrade() -> None:
    _recreate(skip_partner=False)
