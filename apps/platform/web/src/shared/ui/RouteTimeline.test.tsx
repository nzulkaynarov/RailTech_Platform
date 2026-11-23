import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EdsDecision, EdsRouteStep } from "../api/generated/model";
import { renderUi } from "../../test/renderUi";
import { RouteTimeline } from "./RouteTimeline";

const person = (name: string) => ({ id: name, crm_user_id: 1, full_name: name });
const steps: EdsRouteStep[] = [
  {
    label: "Бухгалтер",
    status: "approved",
    decided_by: person("Каримова Н."),
    decided_at: "2026-11-21T09:00:00Z",
    comment: "сумма сверена",
  },
  { label: "Директор", status: "current", decided_by: null, decided_at: null, comment: null },
];
const decision = (over: Partial<EdsDecision>): EdsDecision => ({
  round: 1,
  step: 1,
  decision: "approve",
  comment: null,
  by: person("Каримова Н."),
  at: "2026-11-21T09:00:00Z",
  ...over,
});

function renderRoute(decisions: EdsDecision[]) {
  renderUi(
    <RouteTimeline
      label="Маршрут"
      steps={steps}
      decisions={decisions}
      author={{
        name: "Рахимов Д.",
        at: "2026-11-20T08:00:00Z",
        title: (name) => `Автор: ${name}`,
      }}
      stepTitle={(step) => `${step.label}: ${step.status}`}
      decisionTitle={(d) => `решение ${d.decision} круг ${String(d.round)}`}
    />,
  );
  return within(screen.getByRole("list", { name: "Маршрут" })).getAllByRole("listitem");
}

describe("RouteTimeline", () => {
  it("автор, затем шаги: решение, уже стоящее на шаге, второй раз не печатается", () => {
    const rows = renderRoute([decision({})]);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Автор: Рахимов Д.");
    expect(rows[1]).toHaveTextContent("Бухгалтер: approved");
    expect(rows[1]).toHaveTextContent("сумма сверена");
    expect(rows[2]).toHaveTextContent("Директор: current");
    expect(screen.queryByText(/решение approve/)).toBeNull();
  });

  it("решение прошлого круга (возврат) встаёт перед своим шагом в одной ленте", () => {
    const rows = renderRoute([
      decision({
        round: 1,
        decision: "return",
        comment: "нет счёта",
        at: "2026-11-20T12:00:00Z",
      }),
      decision({ round: 2 }),
    ]);
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent("решение return круг 1");
    expect(rows[1]).toHaveTextContent("нет счёта");
    expect(rows[2]).toHaveTextContent("Бухгалтер: approved");
    expect(screen.getAllByText(/Каримова Н\./)).toHaveLength(2);
  });

  it("решение, не подошедшее ни к одному шагу (шагов стало меньше), не теряется", () => {
    const rows = renderRoute([
      decision({}),
      decision({
        round: 1,
        step: 3,
        decision: "return",
        comment: "прошлый круг, шаг 3",
        at: "2026-11-19T12:00:00Z",
      }),
    ]);
    expect(rows).toHaveLength(4);
    const orphan = rows.find((r) => r.textContent.includes("прошлый круг, шаг 3"));
    expect(orphan).toHaveTextContent("решение return круг 1");
  });
});
