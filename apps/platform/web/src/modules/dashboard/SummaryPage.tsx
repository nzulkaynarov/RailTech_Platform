import { Column } from "@ant-design/charts";
import { Alert, Button, Card } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useAuth } from "../../app/auth/useAuth";
import { usePollQuery } from "../../shared/api/polling";
import { useGetQueue, useGetQueueCards } from "../../shared/api/generated/platform-bff";
import type { DueLabel, QueueItem } from "../../shared/api/generated/model";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { CounterCard, CounterGrid } from "../../shared/ui/CounterCard";
import { PageHeader } from "../../shared/ui/PageHeader";
import { objectLink } from "../objectLinks";
import "./summary.css";

const DUE_ORDER: readonly DueLabel[] = ["overdue", "today", "tomorrow", "later"];
const PENDING_BLOCKS = ["requests", "profit", "targets"] as const;
const STUCK_LIMIT = 5;

function countByDue(items: readonly QueueItem[]) {
  return DUE_ORDER.map((due) => ({
    due,
    value: items.filter((item) => item.due_label === due).length,
  }));
}

/** Главная · Сводка: счётчики и сроки из очереди; блоки без источника данных показывают свою раскладку. */
export function SummaryPage() {
  const { t } = useTranslation(["modules"]);
  const { me } = useAuth();
  const role = me.active_role ?? undefined;
  const params = role ? { role } : undefined;
  const poll = usePollQuery();
  const queue = useGetQueue(params, { query: poll });
  const cards = useGetQueueCards(params, { query: poll });
  const title = t("modules:dashboard.sections.summary");
  useDocumentTitle(title);

  const items = queue.data?.items ?? [];
  const label = (due: DueLabel) => t(`modules:dashboard.summary.due.${due}`, { defaultValue: due });
  const data = countByDue(items).map(({ due, value }) => ({ due: label(due), value }));
  const chartText = data.map((row) => `${row.due}: ${String(row.value)}`).join(", ");
  const stuck = items.filter((item) => item.due_label === "overdue").slice(0, STUCK_LIMIT);

  return (
    <div className="pf-summary">
      <PageHeader title={title} />
      {queue.isError ? (
        <Alert
          type="error"
          showIcon
          message={t("modules:dashboard.summary.loadError")}
          action={
            <Button
              size="small"
              onClick={() => {
                void queue.refetch();
                void cards.refetch();
              }}
            >
              {t("modules:dashboard.summary.retry")}
            </Button>
          }
        />
      ) : null}
      {cards.data && cards.data.cards.length > 0 ? (
        <CounterGrid>
          {cards.data.cards.map((card) => (
            <CounterCard key={card.key} label={card.label} value={card.count} to={card.path} />
          ))}
        </CounterGrid>
      ) : null}
      <div className="pf-summary-grid">
        <Card title={t("modules:dashboard.summary.byDue")}>
          <div role="img" aria-label={chartText}>
            <Column
              data={data}
              xField="due"
              yField="value"
              height={240}
              animate={false}
              axis={{ x: { title: false }, y: { title: false, tickCount: 4 } }}
              style={{ fill: "#1668dc", maxWidth: 56 }}
              label={{ text: "value", position: "inside", style: { fill: "#fff" } }}
            />
          </div>
        </Card>
        <Card title={t("modules:dashboard.summary.stuck")}>
          {stuck.length === 0 ? (
            <p className="pf-hint">{t("modules:dashboard.summary.noStuck")}</p>
          ) : (
            <ul className="pf-summary-list">
              {stuck.map((item) => (
                <li key={item.id}>
                  <Link to={objectLink(item.object)}>{item.title}</Link>
                  <span className="pf-hint">{item.subtitle}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {PENDING_BLOCKS.map((block) => (
          <Card
            key={block}
            title={t(`modules:dashboard.summary.blocks.${block}`)}
            className="pf-summary-pending"
          >
            <p className="pf-hint">{t("modules:dashboard.summary.noData")}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
