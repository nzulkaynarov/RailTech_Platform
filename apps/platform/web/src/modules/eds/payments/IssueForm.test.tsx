import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MOCK_NO_BANK_KEY } from "../../../mocks/fixtures/company";
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

  it("нет банковских реквизитов: плашка до клика — на вкладке «К выставлению» и у кнопки, кнопка неактивна; ссылки в закрытые Настройки у менеджера нет (D26G-6)", async () => {
    window.localStorage.setItem(MOCK_NO_BANK_KEY, "1");
    signIn("universal@demo.example");
    renderAt("/eds/payments?show=to_issue");

    const main = await screen.findByRole("main");
    const notice = await within(main).findByText(
      "Нет банковских реквизитов компании — счёт не выставить.",
    );
    expect(notice).toBeVisible();
    expect(
      within(main).getByText("Заполняет администратор: Настройки · Реквизиты и бланк."),
    ).toBeVisible();
    expect(within(main).queryByRole("link", { name: "Открыть «Реквизиты и бланк»" })).toBeNull();

    fireEvent.click(
      await screen.findByRole("link", { name: `Показать счёт ${DRAFT} в боковом окне` }),
    );
    const form = await within(await panelEl()).findByRole("form", { name: "Выставить счёт" });
    expect(
      within(form).getByText("Нет банковских реквизитов компании — счёт не выставить."),
    ).toBeVisible();
    expect(within(form).getByRole("button", { name: "Выставить счёт" })).toBeDisabled();
    expect(findInvoice(143)?.status).toBe("draft");
  });

  it("реквизиты есть — плашки нет ни на вкладке, ни у кнопки", async () => {
    const panel = await openDraft("accountant@demo.example");

    await within(panel).findByRole("form", { name: "Выставить счёт" });
    expect(
      screen.queryByText("Нет банковских реквизитов компании — счёт не выставить."),
    ).toBeNull();
  });
});
