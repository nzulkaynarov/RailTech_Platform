import { Tag, Timeline, Typography } from "antd";

import type { DecisionsResponse } from "../api/generated/model";
import {
  decisionColor,
  decisionErrorLabel,
  reasonLabel,
  rejectedReason,
  sourceLabel,
  stageLabel,
  transitionReason,
} from "../domain/labels";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";
import { PageState } from "./PageState";

type Item = DecisionsResponse["items"][number];
type Query = {
  data: DecisionsResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
};

const stage = (code: string | null | undefined): string =>
  code ? stageLabel(code).label : t.common.none;

/** Человекочитаемая строка решения: без кодов стадий, источников и служебных причин. */
function describeDecision(item: Item): string {
  if (item.kind === "transition") {
    const why = transitionReason(item.reason);
    const head = `${stage(item.from_stage)} → ${stage(item.to_stage)} (${sourceLabel(item.source)})`;
    return why ? `${head}: ${why}` : head;
  }
  if (item.error) return decisionErrorLabel(item.error);
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
      <div
        title={
          item.kind === "qualifier" && item.error
            ? `${t.lead.decisionFailedHint}: ${item.error}`
            : undefined
        }
      >
        {describeDecision(item)}
      </div>
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

/**
 * «Почему система так решила»: прогоны квалификатора и переходы стадий (SPEC §10.1).
 * Ошибка запроса — `SectionError` с «Повторить», а не «решений нет».
 */
export function DecisionsPanel({ query }: { query: Query }) {
  const items = query.data?.items ?? [];
  return (
    <PageState
      query={query}
      variant="section"
      empty={!items.length && { title: t.lead.noDecisions, hint: t.lead.noDecisionsHint }}
    >
      <Timeline
        items={items.map((item) => ({
          key: `${item.kind}-${String(item.id)}`,
          color: decisionColor(item.kind, item.kind === "qualifier" && item.escalated),
          children: <DecisionBody item={item} />,
        }))}
      />
    </PageState>
  );
}
