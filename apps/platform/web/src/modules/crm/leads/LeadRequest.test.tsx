import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { readLeads, resetLeads, writeLeads } from "../../../mocks/fixtures/leads";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

beforeEach(() => {
  resetLeads();
});

async function panel(lead: string): Promise<HTMLElement> {
  signIn("manager@demo.example");
  renderAt(`/crm/leads?lead=${lead}&panel=open&tab=card`);
  const element = await panelEl();
  await within(element).findByRole("heading", { level: 3 });
  return element;
}

function withRequest(request: {
  deal: number;
  number: string | null;
  transfer: "done" | "failed";
}) {
  const state = readLeads();
  const lead = state.leads.find((l) => l.row.lead === "L-2033");
  if (lead) lead.card.request = request;
  writeLeads(state);
}

/** КЛИЕНТ-1: после заявки карточка лида её показывает, главная «Создать заявку» уходит (дубль не соблазняет). */
describe("карточка лида: заявка, созданная из лида", () => {
  it("без заявки — главная «Создать заявку»", async () => {
    const element = await panel("L-2033");
    const create = within(element).getByRole("link", { name: "Создать заявку" });
    expect(create).toBeVisible();
    expect(within(element).queryByTestId("lead-request")).toBeNull();
    expect(within(element).queryByText("Ещё одна заявка")).toBeNull();
  });

  it("с заявкой — «Заявка ПР-… создана» со ссылкой, «Ещё одна заявка» вторая кнопка", async () => {
    withRequest({ deal: 301, number: "ПР-2026-018", transfer: "done" });
    const element = await panel("L-2033");
    const line = await within(element).findByTestId("lead-request");
    expect(line).toHaveTextContent("Заявка ПР-2026-018 создана");
    expect(within(line).getByRole("link", { name: "Открыть заявку" })).toHaveAttribute(
      "href",
      expect.stringContaining("/crm/clients/3"),
    );
    expect(within(element).queryByRole("link", { name: "Создать заявку" })).toBeNull();
    const another = within(element).getByRole("link", { name: "Ещё одна заявка" });
    expect(another.className).not.toContain("ant-btn-primary");
  });

  it("номера ещё нет и передача не прошла — без выдуманного номера", async () => {
    withRequest({ deal: 302, number: null, transfer: "failed" });
    const element = await panel("L-2033");
    expect(await within(element).findByTestId("lead-request")).toHaveTextContent(
      "Заявка создана, но не передана в учёт",
    );
  });

  it("приглашение: сырые значения канала («both») словами, незнакомое — «другой канал»", async () => {
    const state = readLeads();
    const lead = state.leads.find((l) => l.row.lead === "L-2033");
    if (lead?.card.invitation) lead.card.invitation = { ...lead.card.invitation, channel: "both" };
    writeLeads(state);
    const element = await panel("L-2033");
    expect(await within(element).findByText(/канал: Почта и Telegram/)).toBeVisible();
    expect(screen.queryByText(/both/)).toBeNull();
  });
});
