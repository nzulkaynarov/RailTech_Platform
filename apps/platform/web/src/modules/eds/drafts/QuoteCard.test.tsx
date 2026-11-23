import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readQuotes, writeQuotes } from "../../../mocks/fixtures/approvals";
import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { decisionEl, openSideTab, panelEl } from "../../../test/panel";

setupApprovalTests();

const QUOTE = (n: number) => `/eds/drafts/${encodeURIComponent(`КП-2026/${String(n)}`)}`;

describe("Карточка КП: одно место для каждого сведения (ЕД-7)", () => {
  it("форма одобрения — в центре; вкладки окна — «Сведения» и «Маршрут», вкладки «Одобрение» нет", async () => {
    signIn("director@demo.example");
    renderAt(QUOTE(115));

    const center = await decisionEl();
    expect(await within(center).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    const side = await panelEl();
    const tabs = within(side)
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    expect(tabs).toEqual(["Сведения", "Маршрут"]);
  });

  it("маршрут — только в «Маршруте»: в центре заголовка «Маршрут одобрения» нет, в окне — одна лента", async () => {
    signIn("director@demo.example");
    renderAt(QUOTE(115));
    await decisionEl();

    expect(screen.queryByRole("heading", { name: "Маршрут одобрения" })).toBeNull();
    const route = await openSideTab("Маршрут");
    expect(within(route).getAllByRole("list", { name: "Маршрут одобрения" })).toHaveLength(1);
    expect(within(route).getByText("Директор: ждёт решения")).toBeVisible();
  });

  it("номер заявки — один раз, в «Сведениях»; исходящий номер — не в шапке, а в «Сведениях»", async () => {
    signIn("director@demo.example");
    renderAt(QUOTE(113));
    expect(await screen.findByRole("heading", { level: 1, name: "КП-2026/113" })).toBeVisible();

    const facts = await openSideTab("Сведения");
    expect(within(facts).getAllByText("ИСХ-027/26")).toHaveLength(1);
    expect(screen.getAllByText("ИСХ-027/26")).toHaveLength(1);
    expect(within(facts).getAllByText("ЗВ-2026-101", { selector: "a" })).toHaveLength(1);
    expect(screen.getAllByText(/ЗВ-2026-101/, { selector: "a, span, div, dd" })).toHaveLength(1);
  });

  it("комментарии клиента — во вкладке «Обсуждение»; нет комментариев — нет и вкладки", async () => {
    signIn("director@demo.example");
    renderAt(QUOTE(113));
    await screen.findByRole("heading", { level: 1, name: "КП-2026/113" });

    const chat = await openSideTab("Обсуждение");
    expect(
      within(chat).getByText("Можно разбить поставку щебня на две партии по 1000 т?"),
    ).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Комментарии клиента" })).toBeNull();
  });

  it("без комментариев клиента вкладки «Обсуждение» нет", async () => {
    signIn("director@demo.example");
    writeQuotes(
      readQuotes().map((q) => (q.number === "КП-2026/113" ? { ...q, client_comments: [] } : q)),
    );
    renderAt(QUOTE(113));
    await screen.findByRole("heading", { level: 1, name: "КП-2026/113" });
    const side = await panelEl();
    await within(side).findByRole("tab", { name: "Сведения" });
    expect(within(side).queryByRole("tab", { name: "Обсуждение" })).toBeNull();
  });

  it("старая ссылка ?panel=open&tab=approve ведёт к форме в центре", async () => {
    signIn("director@demo.example");
    const { router } = renderAt(`${QUOTE(116)}?panel=open&tab=approve`);

    const center = await decisionEl();
    expect(await within(center).findByRole("form", { name: "Одобрение КП" })).toBeVisible();
    await screen.findByRole("heading", { level: 1, name: "КП-2026/116" });
    expect(router.state.location.search).toBe("");
  });

  it("заменённая версия: ссылка на актуальную — без неё в карточке-истории некуда идти", async () => {
    signIn("director@demo.example");
    renderAt("/eds/drafts/40000000-0000-4000-8000-000000001150");

    const link = await screen.findByRole("link", { name: "Открыть версию 2" });
    expect(link).toHaveAttribute("href", `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
  });
});
