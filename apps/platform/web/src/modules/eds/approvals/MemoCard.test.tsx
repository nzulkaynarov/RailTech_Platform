import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readMemos, writeMemos } from "../../../mocks/fixtures/approvals";
import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { decisionEl, openSideTab, panelEl } from "../../../test/panel";

setupApprovalTests();

const MEMO = (ref: string) => `/eds/approvals/${encodeURIComponent(ref)}`;
const person = (id: number, name: string) => ({ id, crm_user_id: id, full_name: name });

/** СЗ-2026/015: директор сначала вернул, потом согласовал; бухгалтер ждёт — решение одно на шаге, возврат — перед ним. */
function withDecisions() {
  writeMemos(
    readMemos().map((m) =>
      m.number === "СЗ-2026/015"
        ? {
            ...m,
            decisions: [
              {
                round: 1,
                step: 1,
                decision: "return" as const,
                comment: "нужен счёт",
                by: person(1, "Демо Директоров"),
                at: "2026-10-26T12:00:00Z",
              },
              {
                round: 2,
                step: 1,
                decision: "approve" as const,
                comment: null,
                by: person(1, "Демо Директоров"),
                at: "2026-10-27T12:00:00Z",
              },
            ],
          }
        : m,
    ),
  );
}

describe("Карточка согласования: маршрут и решения — одна лента (ЕД-7)", () => {
  it("отдельного списка «Решения» нет; возврат прошлого круга стоит в «Маршруте» перед шагом, согласование — один раз", async () => {
    withDecisions();
    signIn("director@demo.example");
    renderAt(MEMO("СЗ-2026/015"));
    await decisionEl();

    expect(screen.queryByRole("heading", { name: "Решения" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Маршрут согласования" })).toBeNull();
    const route = await openSideTab("Маршрут");
    const rows = within(
      within(route).getByRole("list", { name: "Маршрут согласования" }),
    ).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Автор:");
    expect(rows[1]).toHaveTextContent("Возвращено на доработку");
    expect(rows[1]).toHaveTextContent("нужен счёт");
    expect(rows[2]).toHaveTextContent("Директор: согласовано");
    expect(rows[3]).toHaveTextContent("Бухгалтер: ждёт решения");
    expect(within(route).getAllByText(/Демо Директоров/)).toHaveLength(2);
  });

  it("автор и дата — в первой точке «Маршрута», а не второй раз в «Сведениях»", async () => {
    signIn("director@demo.example");
    renderAt(MEMO("СЗ-2026/014"));
    await decisionEl();

    const facts = await openSideTab("Сведения");
    expect(within(facts).queryByText("От кого", { selector: "dt" })).toBeNull();
    expect(within(facts).queryByText("Дата", { selector: "dt" })).toBeNull();
    expect(within(facts).getByText("Кому", { selector: "dt" })).toBeVisible();
  });

  it("форма согласования — в центре; вкладки «Согласование» в окне нет", async () => {
    signIn("director@demo.example");
    renderAt(MEMO("СЗ-2026/014"));

    const center = await decisionEl();
    expect(
      await within(center).findByRole("form", { name: "Согласование документа" }),
    ).toBeVisible();
    const side = await panelEl();
    await within(side).findByRole("tab", { name: "Сведения" });
    expect(within(side).queryByRole("tab", { name: "Согласование" })).toBeNull();
  });

  it("старая ссылка ?panel=open&tab=agree ведёт к форме и снимает параметры окна", async () => {
    signIn("director@demo.example");
    const { router } = renderAt(`${MEMO("СЗ-2026/014")}?panel=open&tab=agree`);

    const center = await decisionEl();
    expect(
      await within(center).findByRole("form", { name: "Согласование документа" }),
    ).toBeVisible();
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
  });
});
