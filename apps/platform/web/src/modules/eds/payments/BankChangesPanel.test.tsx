import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { renderAt, setupPaymentTests, signIn } from "../../../test/paymentsKit";

setupPaymentTests();

const PATH = "/crm/clients?kind=bank_changes";

async function card() {
  const list = await screen.findByRole("list", { name: "Запросы на смену реквизитов" });
  return within(list).getByRole("listitem");
}

describe("Счета и оплаты · смена реквизитов", () => {
  it("фильтр с числом, запрос показывает старые и новые реквизиты", async () => {
    signIn("accountant@demo.example");
    renderAt(PATH);

    expect(
      await screen.findByText("Смена реквизитов · 1", { selector: ".ant-segmented-item-label" }),
    ).toBeVisible();
    const row = await card();
    expect(within(row).getByText(/20208000123456789001/)).toBeVisible();
    expect(within(row).getByText(/20208000555566667777/)).toBeVisible();
    expect(within(row).getByText("На проверке")).toBeVisible();
  });

  it("подтверждение спрашивает и убирает запрос из очереди", async () => {
    signIn("accountant@demo.example");
    renderAt(PATH);
    const row = await card();

    fireEvent.click(within(row).getByRole("button", { name: "Подтвердить" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Подтвердить" }));

    expect(await screen.findByText("Запросов на проверке нет")).toBeVisible();
  });

  it("отклонение требует причину и показывает её", async () => {
    signIn("accountant@demo.example");
    renderAt(PATH);
    const row = await card();

    fireEvent.click(within(row).getByRole("button", { name: "Отклонить" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Отклонить" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Причина отказа"), {
      target: { value: "Нет письма банка" },
    });
    fireEvent.click(confirm);

    expect(await screen.findByText("Запросов на проверке нет")).toBeVisible();
    const filter = screen.getByLabelText("Показать запросы");
    fireEvent.click(within(filter).getByText("Все"));
    expect(await screen.findByText(/Нет письма банка/)).toBeVisible();
  });

  it("устаревший запрос нельзя подтвердить, ошибка конфликта показывается словами", async () => {
    server.use(
      http.get("*/eds/payments/bank-changes", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              company_id: "2",
              company_name: "ООО Старый",
              company_inn: "",
              company_archived: false,
              status: "pending",
              stale: true,
              old_bank_details: "р/с 1",
              new_bank_details: "р/с 2",
              requested_by_name: "Имя",
              requested_by_email: "",
              requested_ip: null,
              created_at: "2026-11-08T10:15:00+05:00",
              decided_at: null,
              decided_by_name: null,
              reject_reason: null,
            },
          ],
          pending_count: 1,
        }),
      ),
    );
    signIn("accountant@demo.example");
    renderAt(PATH);
    const row = await card();

    expect(within(row).getByRole("button", { name: "Подтвердить" })).toBeDisabled();
    expect(within(row).getByText(/подтвердить нельзя/)).toBeVisible();
  });

  it("без полного доступа кнопок решения нет", async () => {
    signIn("manager@demo.example");
    renderAt(PATH);
    const row = await card();

    expect(within(row).queryByRole("button", { name: "Подтвердить" })).toBeNull();
    await waitFor(() => {
      expect(within(row).queryByRole("button", { name: "Отклонить" })).toBeNull();
    });
  });
});
