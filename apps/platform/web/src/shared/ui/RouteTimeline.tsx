import type { ReactNode } from "react";

import type { EdsDecision, EdsRouteStep } from "../api/generated/model";
import { useFormat } from "../lib/useFormat";
import { History, type HistoryItem } from "./History";
import { routeStepState } from "./routeStepState";

import "./ui.css";

export interface RouteTimelineProps {
  label: string;
  steps: readonly EdsRouteStep[];
  /** Решения по кругам маршрута; решение, которое уже стоит на своём шаге, второй раз не печатается */
  decisions?: readonly EdsDecision[];
  /** Автор документа — первая точка ленты */
  author?: { name: string; at: string; title: (name: string) => string } | null;
  stepTitle: (step: EdsRouteStep) => ReactNode;
  decisionTitle: (decision: EdsDecision) => ReactNode;
}

const sameInstant = (a: string | null, b: string) => a !== null && Date.parse(a) === Date.parse(b);

/**
 * «Маршрут» карточки (ЕД-7): одна лента шагов и решений. Шаг несёт своё последнее решение (кто, когда, комментарий), а
 * решения прошлых кругов (возврат на доработку) встают перед шагом, к которому относятся, — списка «Решения» отдельно нет.
 */
export function RouteTimeline({
  label,
  steps,
  decisions = [],
  author,
  stepTitle,
  decisionTitle,
}: RouteTimelineProps) {
  const { date } = useFormat();
  const items: HistoryItem[] = [];
  if (author) {
    items.push({
      state: "done",
      title: author.title(author.name),
      meta: date(author.at, "datetime"),
    });
  }
  steps.forEach((step, index) => {
    const earlier = decisions
      .filter((d) => d.step === index + 1 && !sameInstant(step.decided_at, d.at))
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    for (const d of earlier) {
      items.push({
        state: "done",
        title: decisionTitle(d),
        meta: (
          <>
            {`${date(d.at, "datetime")} · ${d.by.full_name}`}
            {d.comment ? <p className="pf-dec-note">{d.comment}</p> : null}
          </>
        ),
      });
    }
    items.push({
      state: routeStepState(step.status),
      title: stepTitle(step),
      meta: (
        <>
          {step.decided_at && step.decided_by
            ? `${date(step.decided_at, "datetime")} · ${step.decided_by.full_name}`
            : null}
          {step.comment ? <p className="pf-dec-note">{step.comment}</p> : null}
        </>
      ),
    });
  });
  // Decisions of earlier rounds whose step no longer exists (a shorter route on resubmission) stay in the history.
  const orphans = decisions
    .filter((d) => d.step < 1 || d.step > steps.length)
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const authorItems = author ? 1 : 0;
  items.splice(
    authorItems,
    0,
    ...orphans.map((d): HistoryItem => ({
      state: "done",
      title: decisionTitle(d),
      meta: (
        <>
          {`${date(d.at, "datetime")} · ${d.by.full_name}`}
          {d.comment ? <p className="pf-dec-note">{d.comment}</p> : null}
        </>
      ),
    })),
  );
  return <History items={items} label={label} />;
}
