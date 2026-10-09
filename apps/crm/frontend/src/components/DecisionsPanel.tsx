import { Empty, Tag, Timeline, Typography } from "antd";

import type { DecisionsResponse } from "../api/generated/model";
import {
  reasonLabel,
  rejectedReason,
  sourceLabel,
  stageLabel,
  transitionReason,
} from "../domain/labels";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";

type Item = DecisionsResponse["items"][number];

const stage = (code: string | null | undefined): string =>
  code ? stageLabel(code).label : t.common.none;

/** Человекочитаемая строка решения: без кодов стадий, источников и служебных причин. */
function describeDecision(item: Item): string {
  if (item.kind === "transition") {
    const why = transitionReason(item.reason);
    const head = `${stage(item.from_stage)} → ${stage(item.to_stage)} (${sourceLabel(item.source)})`;
    return why ? `${head}: ${why}` : head;
  }
  if (item.error) return `⚠️ ${item.error}`;
  const parts = [
    `${t.lead.proposed}: ${stage(item.proposed_stage)}`,
    item.applied_stage ? `${t.lead.applied}: ${stage(item.applied_stage)}` : "",
    item.rejected_reason ? `${t.lead.rejected}: ${rejectedReason(item.rejected_reason)}` : "",
    `${t.leads.score} ${String(item.score_before)} → ${String(item.score_after)}`,
  ];
  return parts.filter(Boolean).join(" · ");
}

function DecisionBody({ item }: { item: Item }) {
  return (
    <div>
      <Typography.Text type="secondary">{formatWhen(item.at)}</Typography.Text>
      <div>{describeDecision(item)}</div>
      {item.kind === "qualifier" && item.triggers_fired.length ? (
        <div>
          {t.lead.triggers}:{" "}
          {item.triggers_fired.map((code) => (
            <Tag key={code}>{reasonLabel(code)}</Tag>
          ))}
        </div>
      ) : null}
      {item.kind === "qualifier" && item.next_best_action ? (
        <Typography.Text type="secondary">{item.next_best_action}</Typography.Text>
      ) : null}
    </div>
  );
}

/** «Почему система так решила»: прогоны квалификатора и переходы стадий (SPEC §10.1). */
export function DecisionsPanel({ decisions }: { decisions: DecisionsResponse | undefined }) {
  if (!decisions?.items.length) return <Empty description={t.lead.noDecisions} />;
  return (
    <Timeline
      items={decisions.items.map((item) => ({
        key: `${item.kind}-${String(item.id)}`,
        color: item.kind === "transition" ? "blue" : item.escalated ? "red" : "gray",
        children: <DecisionBody item={item} />,
      }))}
    />
  );
}
