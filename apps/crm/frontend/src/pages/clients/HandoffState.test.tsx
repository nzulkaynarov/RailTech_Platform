import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientDetail } from "../../api/generated/model";
import { handoffErrorText } from "./handoffText";
import { HandoffState } from "./HandoffState";

const makeCustomer = vi.fn();
vi.mock("../../api/generated/crm", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/generated/crm")>()),
  makeCustomer: (...args: unknown[]) => makeCustomer(...args) as unknown,
}));

const client = (patch: Partial<ClientDetail>): ClientDetail => ({
  id: 5,
  name: "ООО Тест",
  inn: "123456789",
  segment: null,
  owner_user_id: null,
  is_active: true,
  notes: null,
  created_at: "2026-10-20T10:00:00Z",
  erp_company_id: null,
  erp_handoff_status: null,
  erp_handoff_error: null,
  identities: [],
  candidates: [],
  leads: [
    { id: 3, display_name: "Старый", stage: "customer", created_at: "2026-10-01T10:00:00Z" },
    { id: 9, display_name: "Новый", stage: "customer", created_at: "2026-10-18T10:00:00Z" },
  ] as ClientDetail["leads"],
  service_requests: [],
  ...patch,
});

function show(data: ClientDetail, canWrite = true) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AntApp>
        <HandoffState client={data} canWrite={canWrite} />
      </AntApp>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  makeCustomer.mockReset().mockResolvedValue({ id: 5 });
});

describe("HandoffState (состояние передачи в бэк-офис)", () => {
  it.each([null, "done"] as const)("shows nothing when the status is %s", (status) => {
    show(client({ erp_handoff_status: status }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says the client is being handed off", () => {
    show(client({ erp_handoff_status: "pending" }));
    expect(screen.getByText("Передаётся в бэк-офис")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("mentions the last transient error while it keeps retrying", () => {
    show(client({ erp_handoff_status: "pending", erp_handoff_error: "erp_unavailable" }));
    expect(screen.getByText(/ERP не отвечает/)).toBeInTheDocument();
    expect(screen.getByText(/повторится сама/)).toBeInTheDocument();
  });

  it("explains the INN conflict in words, not as a code", () => {
    show(client({ erp_handoff_status: "failed", erp_handoff_error: "erp_inn_conflict" }));
    expect(screen.getByText("Передача в бэк-офис не удалась")).toBeInTheDocument();
    expect(screen.getByText(/ИНН этого клиента уже есть в бэк-офисе/)).toBeInTheDocument();
    expect(screen.queryByText("erp_inn_conflict")).not.toBeInTheDocument();
  });

  it("retries through the same make_customer call for the latest lead of the client", async () => {
    show(client({ erp_handoff_status: "failed", erp_handoff_error: "erp_unavailable" }));
    fireEvent.click(screen.getByRole("button", { name: "Повторить передачу" }));
    await waitFor(() => {
      expect(makeCustomer).toHaveBeenCalledWith(9, { client_id: 5, new_client_name: null });
    });
  });

  it("hides the retry button from users who cannot write clients", () => {
    show(client({ erp_handoff_status: "failed", erp_handoff_error: "erp_unavailable" }), false);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("Передача в бэк-офис не удалась")).toBeInTheDocument();
  });
});

describe("handoffErrorText", () => {
  it.each([
    ["handoff_enqueue_failed", /в очередь/],
    ["handoff_no_consent", /согласие/],
    ["unknown_code_x", /unknown_code_x/],
  ])("%s", (code, expected) => {
    expect(handoffErrorText(code)).toMatch(expected);
  });
});
