import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { panelEl, renderAt, signIn, setupIntegrationsTests } from "./testkit";

setupIntegrationsTests();

async function mailPanel(email = "admin@demo.example"): Promise<HTMLElement> {
  signIn(email);
  renderAt("/admin/integrations?card=mail&panel=open");
  await screen.findByRole("heading", { name: "Приём: общий ящик (IMAP)" });
  return panelEl();
}

describe("карточка «Почта» · приём (W18A-P2)", () => {
  it("админ видит ящик, пароль приложения — только маской; «Проверить приём» — итог словами", async () => {
    const side = await mailPanel();
    expect(await within(side).findByText("imap.mail.example:993")).toBeVisible();
    expect(within(side).getByText("•••• x7Qa")).toBeVisible();
    expect(within(side).getByText("Включён — по кнопке «Подсказать»")).toBeVisible();
    fireEvent.click(within(side).getByRole("button", { name: "Проверить приём" }));
    expect(await within(side).findByText("Ящик открывается: писем в папке — 128")).toBeVisible();
  });

  it("форма приёма: пароль приложения и выключатель помощника, «Что произойдёт»", async () => {
    const side = await mailPanel();
    fireEvent.click(await within(side).findByRole("button", { name: "Настроить приём" }));
    const form = within(side).getByRole("form", { name: "Приём почты" });
    expect(within(form).getByLabelText("Пароль приложения")).toHaveAttribute("type", "password");
    expect(within(form).getByText(/не удаляются и не помечаются/)).toBeVisible();
    expect(within(form).getByRole("checkbox", { name: /Помощник канцелярии/ })).toBeChecked();
  });
});
