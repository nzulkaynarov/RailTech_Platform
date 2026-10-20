import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DealOut } from "../../api/generated/model";
import { DealDialog } from "./DealDialog";

const mutate = vi.fn();
vi.mock("../../api/dealQueries", () => ({
  useDealOptions: () => ({ data: { currency: "UZS", lost_reasons: ["Дорого"] } }),
  useSaveDeal: () => ({ mutate: (...args: unknown[]) => mutate(...args) as unknown }),
}));
vi.mock("../../api/adminQueries", () => ({ useClients: () => ({ data: [] }) }));
vi.mock("../../api/queries", () => ({
  useTeam: () => ({ data: [{ id: 3, full_name: "Азиза" }] }),
}));

const deal = (patch: Partial<DealOut>): DealOut => ({
  id: 11,
  client_id: 1,
  client_name: "ООО Ромашка",
  lead_id: 4,
  title: "Заявка: Ромашка",
  product_key: null,
  amount: "28000000.00",
  currency: "UZS",
  stage: "open",
  expected_close_date: null,
  closed_at: null,
  lost_reason: null,
  owner_user_id: 3,
  created_at: "2026-10-20T10:00:00Z",
  ...patch,
});

function show(item: DealOut) {
  return render(
    <AntApp>
      <DealDialog open deal={item} onClose={() => undefined} />
    </AntApp>,
  );
}

beforeEach(() => {
  mutate.mockReset();
});

describe("DealDialog — зеркальная сделка ERP (I-26)", () => {
  it("название, сумма, валюта и стадия — текстом, не полями; подсказка «Ведётся в бэк-офисе (ERP)»", async () => {
    show(deal({ erp_deal_id: 22, external_stage: "closing" }));
    expect(await screen.findByText(/Ведётся в бэк-офисе \(ERP\)/)).toBeInTheDocument();
    expect(screen.getByText("Заявка: Ромашка")).toBeInTheDocument();
    expect(screen.getByText("28 000 000 UZS")).toBeInTheDocument();
    expect(screen.queryByLabelText("Название")).toBeNull();
    expect(screen.queryByLabelText("Сумма")).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Валюта" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Стадия" })).toBeNull();
    // Поля CRM остаются доступными.
    expect(screen.getByRole("combobox", { name: "Ответственный" })).toBeEnabled();
    expect(screen.getByLabelText("Ожидаемое закрытие")).toBeEnabled();
  });

  it("на сохранение уходят только ответственный и срок", async () => {
    show(deal({ erp_deal_id: 22, external_stage: "closing", stage: "won" }));
    await screen.findByText(/Ведётся в бэк-офисе \(ERP\)/);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(mutate).toHaveBeenCalled();
    });
    const [{ id, body }] = mutate.mock.calls[0] as [{ id: number; body: Record<string, unknown> }];
    expect(id).toBe(11);
    expect(Object.keys(body).sort()).toEqual(["expected_close_date", "owner_user_id"]);
    expect(body).toEqual({ expected_close_date: null, owner_user_id: 3 });
  });

  it("локальная сделка правится целиком, подсказки нет", async () => {
    show(deal({ erp_deal_id: null }));
    expect(await screen.findByLabelText("Название")).toBeEnabled();
    expect(screen.getByLabelText("Сумма")).toBeEnabled();
    expect(screen.queryByText(/Ведётся в бэк-офисе \(ERP\)/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(mutate).toHaveBeenCalled();
    });
    const [{ body }] = mutate.mock.calls[0] as [{ body: Record<string, unknown> }];
    expect(body).toMatchObject({ title: "Заявка: Ромашка", amount: 28000000, stage: "open" });
  });
});
