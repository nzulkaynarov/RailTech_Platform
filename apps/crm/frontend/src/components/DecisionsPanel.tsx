import { Empty, Tag, Timeline, Typography } from "antd";
import dayjs from "dayjs";

import type { DecisionsResponse } from "../api/generated/model";
import { t } from "../i18n/ru";

type Item = DecisionsResponse["items"][number];

function describe(item: Item): string {
  if (item.kind === "transition") {
    const from = t.stage[item.from_stage] ?? item.from_stage;
    const to = t.stage[item.to_stage] ?? item.to_stage;
    return `${from} → ${to} (${item.source}): ${item.reason}`;
  }
  if (item.error) return `⚠️ ${item.error}`;
  const parts = [
    `${t.lead.proposed}: ${t.stage[item.proposed_stage ?? ""] ?? item.proposed_stage ?? t.common.none}`,
    item.applied_stage
      ? `${t.lead.applied}: ${t.stage[item.applied_stage] ?? item.applied_stage}`
      : "",
    item.rejected_reason ? `${t.lead.rejected}: ${item.rejected_reason}` : "",
    `score ${String(item.score_before)} → ${String(item.score_after)}`,
  ];
  return parts.filter(Boolean).join(" · ");
}

/** «Почему система так решила»: прогоны квалификатора и переходы стадий (SPEC §10.1). */
export function DecisionsPanel({ decisions }: { decisions: DecisionsResponse | undefined }) {
  if (!decisions?.items.length) return <Empty description={t.lead.noDecisions} />;
  return (
    <Timeline
      items={decisions.items.map((item) => ({
        key: `${item.kind}-${String(item.id)}`,
        color: item.kind === "transition" ? "blue" : item.escalated ? "red" : "gray",
        children: (
          <div>
            <Typography.Text type="secondary">
              {dayjs(item.at).format("DD.MM HH:mm")}
            </Typography.Text>
            <div>{describe(item)}</div>
            {item.kind === "qualifier" && item.triggers_fired.length ? (
              <div>
                {t.lead.triggers}:{" "}
                {item.triggers_fired.map((code) => (
                  <Tag key={code}>{t.reasons[code] ?? code}</Tag>
                ))}
              </div>
            ) : null}
            {item.kind === "qualifier" && item.next_best_action ? (
              <Typography.Text type="secondary">{item.next_best_action}</Typography.Text>
            ) : null}
          </div>
        ),
      }))}
    />
  );
}
