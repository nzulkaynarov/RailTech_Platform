import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { DealOut } from "../../api/generated/model";
import { DealsTable } from "./DealsTable";

const deal: DealOut = {
  id: 1,
  client_id: 1,
  client_name: "ООО Ромашка",
  lead_id: 4,
  title: "Заявка: Ромашка",
  product_key: null,
  amount: "28000000.00",
  currency: "UZS",
  stage: "won",
  expected_close_date: null,
  closed_at: null,
  lost_reason: null,
  owner_user_id: 3,
  created_at: "2026-10-20T10:00:00Z",
  erp_deal_id: 22,
  external_stage: "closing",
};

const show = (embedded: boolean) =>
  render(
    <MemoryRouter>
      <DealsTable deals={[deal]} embedded={embedded} onEdit={null} />
    </MemoryRouter>,
  );

describe("DealsTable — сумма не рвётся посреди числа (D-9)", () => {
  it.each([true, false])("ячейка суммы без переноса (embedded: %s)", (embedded) => {
    show(embedded);
    // Неразрывные пробелы внутри числа и перед валютой — формат из `formatMoney`.
    const money = ["28", "000", "000", "UZS"].join("\u00a0");
    const cell = screen.getAllByRole("cell").find((c) => c.textContent === money);
    expect(cell).toBeDefined();
    expect(cell).toHaveStyle({ whiteSpace: "nowrap" });
  });

  it("карточка клиента на телефоне: стадия под названием, отдельной колонки нет", () => {
    show(true);
    expect(screen.queryByRole("columnheader", { name: "Стадия" })).toBeNull();
    const title = screen.getByText("Заявка: Ромашка").closest("td");
    expect(title).toHaveTextContent("Выиграна");
    expect(title).toHaveTextContent("#22");
  });

  it("раздел «Сделки»: колонка «Стадия» на месте", () => {
    show(false);
    expect(screen.getByRole("columnheader", { name: "Стадия" })).toBeInTheDocument();
  });
});
