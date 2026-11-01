import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { findInvoice } from "../../../mocks/fixtures/payments";
import { panelEl, renderAt, setupPaymentTests, signIn } from "../../../test/paymentsKit";

setupPaymentTests();

/** Счёт-черновик мока «К выставлению» (D2-4). */
const DRAFT = "СЧ-2026/143";

async function openDraft(user: string) {
  signIn(user);
  renderAt("/eds/payments?show=to_issue");
  fireEvent.click(
    await screen.findByRole("link", { name: `Показать счёт ${DRAFT} в боковом окне` }),
  );
  return panelEl();
}

describe("«Выставить счёт» из Платформы (B-D24-4)", () => {
  it("бухгалтер: черновик — кнопка «Выставить счёт» с правдой о том, что сделает ERP", async () => {
    const panel = await openDraft("accountant@demo.example");

    const form = await within(panel).findByRole("form", { name: "Выставить счёт" });
    const what = within(form).getByRole("group", { name: "Что произойдёт" });
    expect(what).toHaveTextContent("«Выставлен»");
    expect(what).toHaveTextContent("PDF с реквизитами компании");
    expect(what).toHaveTextContent("увидит счёт в кабинете");
    expect(within(form).getByRole("button", { name: "Выставить счёт" })).toBeEnabled();
  });

  it("«Выставить счёт» переводит черновик в «Выставлен» с датой выставления", async () => {
    const panel = await openDraft("universal@demo.example");

    const form = await within(panel).findByRole("form", { name: "Выставить счёт" });
    fireEvent.click(within(form).getByRole("button", { name: "Выставить счёт" }));

    expect((await screen.findAllByText(`Счёт ${DRAFT} выставлен.`)).length).toBeGreaterThan(0);
    const card = findInvoice(143);
    expect(card?.status).toBe("issued");
    expect(card?.issued_at).not.toBeNull();
    expect(within(panel).queryByRole("form", { name: "Выставить счёт" })).toBeNull();
  });

  it("директор (счета только читает): кнопки нет, черновик объяснён словами", async () => {
    const panel = await openDraft("director@demo.example");

    expect(await within(panel).findByText("Счёт ещё не выставлен")).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Выставить счёт" })).toBeNull();
  });
});
