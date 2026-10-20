import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LeadDetail } from "../api/generated/model";
import { LeadActions } from "./LeadActions";
import {
  type ActionRights,
  availableActions,
  clientHandoff,
  leadActionPlan,
  mayHandoffClient,
} from "./leadActionRules";

const makeCustomer = vi.fn();
vi.mock("../api/generated/crm", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/generated/crm")>()),
  makeCustomer: (...args: unknown[]) => makeCustomer(...args) as unknown,
}));

const lead = (patch: Partial<LeadDetail>): LeadDetail => ({
  id: 9,
  display_name: "Азиз",
  language: "ru",
  stage: "customer",
  score: 40,
  owner_mode: "bot",
  assigned_user_id: 7,
  client_id: 5,
  need_summary: null,
  product_interest: [],
  last_lead_msg_at: null,
  created_at: "2026-10-08T10:00:00Z",
  escalation: null,
  qualification: {},
  consent_given_at: null,
  tg_username: null,
  notes_count: 0,
  snoozed_until: null,
  backoffice_mode: "erp",
  client_in_erp: false,
  client_handoff_status: null,
  ...patch,
});

const manager: ActionRights = {
  take: true,
  work: true,
  note: true,
  reply: true,
  clients: true,
  userId: 7,
  isAdmin: false,
};

const STAGES = ["handoff", "in_progress", "won", "lost", "customer"] as const;
const STATUSES = [null, "pending", "failed", "done"] as const;

// Эталон матрицы: «Передать в бэк-офис» у клиента, не переданного в ERP (Q-FIX34-1).
const expectedState = (
  mode: string,
  stage: string,
  inErp: boolean,
  status: (typeof STATUSES)[number],
) => {
  if (mode !== "erp" || stage !== "customer" || inErp) return "none";
  if (status === "pending" || status === "failed") return status;
  return "available";
};

describe("clientHandoff — режим × стадия × client_in_erp × статус передачи", () => {
  const matrix = (["local", "erp"] as const).flatMap((mode) =>
    STAGES.flatMap((stage) =>
      ([false, true] as const).flatMap((inErp) =>
        STATUSES.map((status) => [mode, stage, inErp, status] as const),
      ),
    ),
  );

  it.each(matrix)("%s / %s / в ERP: %s / статус: %s", (mode, stage, inErp, status) => {
    const item = lead({
      backoffice_mode: mode,
      stage,
      client_in_erp: inErp,
      client_handoff_status: status,
    });
    const state = clientHandoff(item);
    expect(state).toBe(expectedState(mode, stage, inErp, status));
    // Кнопку «Передать в бэк-офис» у customer даёт только состояние available.
    if (stage === "customer") {
      expect(availableActions(item, manager).makeCustomer).toBe(state === "available");
    }
  });

  it("лид без клиента: передавать нечего", () => {
    expect(clientHandoff(lead({ client_id: null }))).toBe("none");
    expect(availableActions(lead({ client_id: null }), manager).makeCustomer).toBe(false);
  });

  it("право как у «Сделать клиентом»: нужны права на клиентов и свой лид (или админ)", () => {
    const item = lead({});
    expect(mayHandoffClient(item, manager)).toBe(true);
    expect(mayHandoffClient(item, { ...manager, clients: false })).toBe(false);
    expect(mayHandoffClient(lead({ assigned_user_id: 3 }), manager)).toBe(false);
    expect(mayHandoffClient(lead({ assigned_user_id: 3 }), { ...manager, isAdmin: true })).toBe(
      true,
    );
    expect(availableActions(item, { ...manager, clients: false }).makeCustomer).toBe(false);
  });

  it("кнопка — главное действие и вытесняет «Новую сделку» в «Ещё»", () => {
    const plan = leadActionPlan(lead({}), manager);
    expect(plan.primary).toBe("makeCustomer");
    expect(plan.more).toContain("newDeal");
  });
});

function show(item: LeadDetail, rights: ActionRights = manager) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AntApp>
          <LeadActions lead={item} rights={rights} />
        </AntApp>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  makeCustomer.mockReset().mockResolvedValue({ id: 5 });
});

describe("LeadActions — «Передать в бэк-офис» у клиента не в ERP", () => {
  it("показывает кнопку и зовёт тот же make_customer с клиентом лида, без диалога", async () => {
    show(lead({}));
    fireEvent.click(screen.getByRole("button", { name: "Передать в бэк-офис" }));
    await waitFor(() => {
      expect(makeCustomer).toHaveBeenCalledWith(9, { client_id: 5, new_client_name: null });
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    ["режим local", lead({ backoffice_mode: "local" })],
    ["клиент уже в ERP", lead({ client_in_erp: true, client_handoff_status: "done" })],
    ["передача идёт", lead({ client_handoff_status: "pending" })],
    [
      "передача не удалась (повтор — в карточке состояния)",
      lead({ client_handoff_status: "failed" }),
    ],
    ["лид без клиента", lead({ client_id: null })],
  ])("кнопки нет: %s", (_, item) => {
    show(item);
    expect(screen.queryByRole("button", { name: "Передать в бэк-офис" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Сделать клиентом" })).toBeNull();
  });

  it("кнопки нет без права на клиентов", () => {
    show(lead({}), { ...manager, clients: false });
    expect(screen.queryByRole("button", { name: "Передать в бэк-офис" })).toBeNull();
    expect(makeCustomer).not.toHaveBeenCalled();
  });
});
