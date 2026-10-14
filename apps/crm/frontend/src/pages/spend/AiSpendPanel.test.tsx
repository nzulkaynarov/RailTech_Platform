/** «Расходы» → «Ансамбль» (M3-CRM-09): хук подменён — плитки, превышение, пустая ERP, разрезы. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AiSpendReport, GetAiSpendGroup } from "../../api/generated/model";
import { ApiError } from "../../api/http";
import { AiSpendPanel } from "./AiSpendPanel";

const zero = { calls: 0, failed_calls: 0, input_tokens: 0, output_tokens: 0, fallback_calls: 0 };

function system(name: string, over: Partial<AiSpendReport["systems"][number]> = {}) {
  return {
    system: name,
    daily_usd: name === "crm" ? 2 : 1,
    today_usd: 0,
    today_calls: 0,
    over_today: false,
    period_usd: 0,
    period_calls: 0,
    fallback_calls: 0,
    days_over: 0,
    connected: false,
    ...over,
  };
}

function report(group: GetAiSpendGroup, over: Partial<AiSpendReport> = {}): AiSpendReport {
  const rows =
    group === "day"
      ? [
          {
            key: "2026-10-13",
            ...zero,
            cost_usd: 0,
            by_system: [],
          },
          {
            key: "2026-10-14",
            ...zero,
            calls: 5,
            fallback_calls: 2,
            input_tokens: 48,
            output_tokens: 80,
            cost_usd: 1.7,
            by_system: [
              { system: "crm", cost_usd: 0.5, calls: 3 },
              { system: "erp", cost_usd: 1.2, calls: 2 },
            ],
          },
        ]
      : [
          {
            key: group === "model" ? "fallback-model" : "erp",
            ...zero,
            calls: 2,
            cost_usd: 1.2,
            by_system: [],
          },
        ];
  return {
    date_from: "2026-10-08",
    date_to: "2026-10-14",
    group,
    timezone: "Asia/Tashkent",
    rows,
    totals: {
      ...zero,
      calls: 5,
      fallback_calls: 2,
      input_tokens: 48,
      output_tokens: 80,
      cost_usd: 1.7,
    },
    systems: [
      system("crm", { today_usd: 0.5, period_usd: 0.5, period_calls: 3, connected: true }),
      system("erp", {
        today_usd: 1.2,
        over_today: true,
        period_usd: 1.2,
        period_calls: 2,
        fallback_calls: 1,
        days_over: 1,
        connected: true,
      }),
    ],
    overruns: [{ system: "erp", day: "2026-10-14", cost_usd: 1.2, daily_usd: 1 }],
    erp_connected: true,
    truncated: false,
    fetched_at: "2026-10-14T05:00:00Z",
    ...over,
  };
}

const groups: GetAiSpendGroup[] = [];
let override: Partial<AiSpendReport> = {};
let failure: unknown = null;

vi.mock("../../api/spendQueries", () => ({
  useAiSpend: (_range: { from: string; to: string }, group: GetAiSpendGroup) => {
    groups.push(group);
    return {
      data: failure ? undefined : report(group, override),
      isLoading: false,
      isError: Boolean(failure),
      error: failure,
      refetch: vi.fn(() => Promise.resolve()),
    };
  },
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AntApp>
          <AiSpendPanel days={7} />
        </AntApp>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("AiSpendPanel", () => {
  beforeEach(() => {
    groups.length = 0;
    override = {};
    failure = null;
    // Десктоп: все колонки (на телефоне — только день, сумма и деградации).
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("min-width"),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows totals, per-system budgets and highlights the ERP overrun", () => {
    renderPanel();
    expect(screen.getAllByText("$1,70").length).toBeGreaterThan(0);
    expect(screen.getByText("$0,50 из $2,00")).toBeTruthy();
    expect(screen.getByText("$1,20 из $1,00")).toBeTruthy();
    const statuses = screen.getAllByRole("status").map((s) => s.textContent);
    expect(statuses).toEqual(["В пределах бюджета", "Бюджет превышен"]);
    expect(screen.getByText("ERP: 14.10.2026 — $1,20 при бюджете $1,00")).toBeTruthy();
  });

  it("day table: newest first, CRM/ERP columns and degradations", () => {
    renderPanel();
    const table = screen.getByText("По дням").closest(".ant-card") as HTMLElement;
    const cells = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.textContent);
    expect(cells[0]).toContain("14.10.2026");
    expect(cells[0]).toContain("$1,20");
    expect(cells[1]).toContain("13.10.2026");
    expect(within(table).getByRole("columnheader", { name: "Деградаций" })).toBeTruthy();
  });

  it("slices switch the group of the second query", () => {
    renderPanel();
    expect(groups).toContain("system");
    fireEvent.click(screen.getByText("Модель"));
    expect(groups).toContain("model");
    expect(screen.getByText("Резерв (fallback-model)")).toBeTruthy();
  });

  it("ERP without gateway rows: empty state instead of zeros", () => {
    override = { erp_connected: false, overruns: [] };
    renderPanel();
    expect(screen.getByText("ERP ещё не подключена к шлюзу")).toBeTruthy();
  });

  it("no calls in the period: empty state, no tables", () => {
    override = { totals: { ...zero, cost_usd: 0 }, overruns: [] };
    renderPanel();
    expect(screen.getByText("Вызовов моделей за период не было")).toBeTruthy();
    expect(screen.queryByText("По дням")).toBeNull();
  });

  it("gateway down: explains instead of a generic error", () => {
    failure = new ApiError(502, "upstream_unavailable", "x", { reason: "litellm_unavailable" });
    renderPanel();
    expect(screen.getByText("Журнал расходов шлюза моделей недоступен")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeTruthy();
  });
});
