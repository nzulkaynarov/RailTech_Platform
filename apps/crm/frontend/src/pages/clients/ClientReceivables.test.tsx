import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientDetail, ClientReceivablesOut } from "../../api/generated/model";
import { ClientDetailPage } from "./ClientDetailPage";

const getClient = vi.fn();
const getReceivables = vi.fn();

/** Подставной API: orval вызывает `http` → `fetch`, поэтому подменяем `fetch` по пути запроса. */
function fakeApi(input: string): Promise<Response> {
  const path = input;
  const json = (body: unknown, status = 200) =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  if (path.endsWith("/erp-receivables")) {
    return (getReceivables() as Promise<ClientReceivablesOut>).then(json);
  }
  if (path.endsWith("/contacts")) return json({ contacts: [] });
  if (path.includes("/clients/")) return (getClient() as Promise<ClientDetail>).then(json);
  if (path.includes("/me/permissions")) return json({ permissions: [] });
  return json([]);
}

const client = (patch: Partial<ClientDetail> = {}): ClientDetail => ({
  id: 5,
  name: "ООО Порядок",
  inn: "123456789",
  segment: null,
  owner_user_id: null,
  is_active: true,
  notes: null,
  created_at: "2026-10-20T10:00:00Z",
  erp_company_id: 118,
  erp_handoff_status: "done",
  erp_handoff_error: null,
  identities: [],
  candidates: [],
  leads: [],
  service_requests: [],
  ...patch,
});

function show() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AntApp>
        <MemoryRouter initialEntries={["/clients/5"]}>
          <Routes>
            <Route path="/clients/:id" element={<ClientDetailPage />} />
          </Routes>
        </MemoryRouter>
      </AntApp>
    </QueryClientProvider>,
  );
}

const reply = (patch: Partial<ClientReceivablesOut>): ClientReceivablesOut => ({
  status: "ok",
  receivables: [],
  ...patch,
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(fakeApi));
  getClient.mockReset().mockResolvedValue(client());
  getReceivables.mockReset();
});

describe("Карточка клиента — долг по валютам из ERP (шов 0.3.0)", () => {
  it("shows the debt of every currency separately, without conversion", async () => {
    getReceivables.mockResolvedValue(
      reply({
        receivables: [
          { amount: "1250000.00", currency: "UZS" },
          { amount: "310.50", currency: "USD" },
        ],
      }),
    );
    show();
    const label = await screen.findByText("Долг по счетам");
    const value = label.closest(".ant-descriptions-item")?.textContent ?? "";
    expect(value).toContain(["1", "250", "000"].join(" ") + " UZS");
    expect(value).toContain("310,5 USD");
  });

  it("says there is no debt when ERP returns an empty list", async () => {
    getReceivables.mockResolvedValue(reply({ receivables: [] }));
    show();
    expect(await screen.findByText("Долга нет")).toBeInTheDocument();
  });

  it.each([
    ["ERP не прислала поле", reply({ status: "unavailable", reason: "no_data" })],
    ["ERP ограничила частоту", reply({ status: "unavailable", reason: "rate_limited" })],
    ["ERP недоступна", reply({ status: "unavailable", reason: "erp_unavailable" })],
  ])("hides the block as before when %s", async (_, answer) => {
    getReceivables.mockResolvedValue(answer);
    show();
    await screen.findByText("ООО Порядок");
    await waitFor(() => {
      expect(getReceivables).toHaveBeenCalled();
    });
    expect(screen.queryByText("Долг по счетам")).toBeNull();
    expect(screen.queryByText("Долга нет")).toBeNull();
  });

  it("hides the block when the request itself fails", async () => {
    getReceivables.mockRejectedValue(new Error("network"));
    show();
    await screen.findByText("ООО Порядок");
    await waitFor(() => {
      expect(getReceivables).toHaveBeenCalled();
    });
    expect(screen.queryByText("Долг по счетам")).toBeNull();
  });

  it("does not ask ERP about a client that is not in the back office", async () => {
    getClient.mockResolvedValue(client({ erp_company_id: null, erp_handoff_status: null }));
    show();
    await screen.findByText("ООО Порядок");
    expect(getReceivables).not.toHaveBeenCalled();
    expect(screen.queryByText("Долг по счетам")).toBeNull();
  });
});
