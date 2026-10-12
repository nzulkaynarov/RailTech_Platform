"""deal_titles: названия и владельцы перенесённых сделок по правилу «Клиент — продукт»

Перенос истории в `0015_deals` назвал сделки именем лида («Иван», эмодзи) и отдал их текущему
ответственному. Здесь — те же сделки (созданы переносом: `created_at = closed_at`, название ещё
по старому правилу) получают название `domain/deals.deal_title` и владельца — того, кто закрыл
лида (`stage_transitions.actor_user_id`). Идемпотентно: второй прогон ничего не находит.

Downgrade обратим по правилу: сделки с названием по новому правилу получают старое название
и владельца — ответственного лида (как сделал перенос в 0015).

Revision ID: 0017_deal_titles
Revises: 0016_channel_chat
Create Date: 2026-10-12 17:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_deal_titles"
down_revision: str | None = "0016_channel_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TITLE = "COALESCE(NULLIF(l.display_name, ''), 'Лид #' || l.id)"
NEW_TITLE = """left(
    COALESCE(NULLIF(btrim(c.name), ''), NULLIF(btrim(l.display_name), ''), 'Лид #' || l.id)
    || COALESCE(' — ' || NULLIF(btrim(COALESCE(
        (SELECT p.name FROM products p WHERE p.key = d.product_key), d.product_key
    )), ''), ''),
    255
)"""
CLOSER = """(
    SELECT t.actor_user_id FROM stage_transitions t
    WHERE t.lead_id = l.id AND t.to_stage IN ('won', 'lost')
    ORDER BY t.created_at DESC LIMIT 1
)"""


def _rewrite(title_from: str, title_to: str, owner: str) -> str:
    return f"""
UPDATE deals d
SET title = {title_to}, owner_user_id = {owner}
FROM leads l
LEFT JOIN clients c ON c.id = l.client_id
WHERE d.lead_id = l.id
  AND d.created_at = d.closed_at
  AND l.erased_at IS NULL
  AND d.title = {title_from}
  AND d.title <> {title_to}
"""


def upgrade() -> None:
    op.execute(_rewrite(OLD_TITLE, NEW_TITLE, f"COALESCE({CLOSER}, d.owner_user_id)"))


def downgrade() -> None:
    op.execute(_rewrite(NEW_TITLE, OLD_TITLE, "l.assigned_user_id"))
