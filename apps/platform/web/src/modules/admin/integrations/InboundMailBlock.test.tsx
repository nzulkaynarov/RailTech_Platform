import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetImapMock } from "../../../mocks/inboundMail";
import { openCard, signIn, setupIntegrationsTests } from "./testkit";

setupIntegrationsTests();
beforeEach(() => {
  resetImapMock();
});

/** Почта — своя страница Настроек «Каналы связи · Почта» (SET-IA), а не боковое окно «Подключений». */
async function mailPanel(email = "admin@demo.example"): Promise<HTMLElement> {
  signIn(email);
  const main = await openCard("mail");
  await screen.findByRole("heading", { name: "Приём: общий ящик (IMAP)" });
  return main;
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

  it("форма приёма: пароль приложения и выключатель помощника, без «Что произойдёт» (сохранение настройки)", async () => {
    const side = await mailPanel();
    fireEvent.click(await within(side).findByRole("button", { name: "Настроить приём" }));
    const form = within(side).getByRole("form", { name: "Приём почты" });
    expect(within(form).getByLabelText("Пароль приложения")).toHaveAttribute("type", "password");
    expect(within(side).getByText(/на сервере они не меняются/)).toBeVisible();
    expect(within(form).queryByRole("group", { name: "Что произойдёт" })).toBeNull();
    expect(within(form).getByRole("checkbox", { name: /Помощник канцелярии/ })).toBeChecked();
  });

  it("правило «адресовано лично»: включено по умолчанию, пометку можно сменить и сохранить", async () => {
    const side = await mailPanel();
    expect(
      await within(side).findByText("Сразу сотруднику — пометка «Адресовано лично»"),
    ).toBeVisible();
    fireEvent.click(await within(side).findByRole("button", { name: "Настроить приём" }));
    const form = within(side).getByRole("form", { name: "Приём почты" });
    const rule = within(form).getByRole("checkbox", { name: /Письмо сотруднику в «Кому»/ });
    expect(rule).toBeChecked();
    const label = within(form).getByLabelText("Пометка у такого письма");
    expect(label).toHaveValue("Адресовано лично");
    fireEvent.change(label, { target: { value: "Лично вам" } });
    fireEvent.change(within(form).getByLabelText("Ваш пароль администратора"), {
      target: { value: "admin-pass" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить настройки" }));
    expect(await within(side).findByText("Сразу сотруднику — пометка «Лично вам»")).toBeVisible();

    fireEvent.click(await within(side).findByRole("button", { name: "Настроить приём" }));
    const again = within(side).getByRole("form", { name: "Приём почты" });
    fireEvent.click(within(again).getByRole("checkbox", { name: /Письмо сотруднику в «Кому»/ }));
    expect(within(again).queryByLabelText("Пометка у такого письма")).toBeNull();
  });

  it("«Найти папки» подсказывает «Спам» по флагу сервера; сохранение — с папками", async () => {
    const side = await mailPanel();
    fireEvent.click(await within(side).findByRole("button", { name: "Настроить приём" }));
    const form = within(side).getByRole("form", { name: "Приём почты" });
    fireEvent.click(within(form).getByRole("button", { name: "Найти папки" }));
    expect(await within(form).findByText("Найдено папок: 4")).toBeVisible();
    const spam = within(form).getByLabelText("Папка «Спам»");
    await waitFor(() => {
      expect(spam.closest(".ant-select")).toHaveTextContent("Spam");
    });
    fireEvent.change(within(form).getByLabelText("Ваш пароль администратора"), {
      target: { value: "admin-pass" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить настройки" }));
    expect(await within(side).findByText("INBOX, Spam (спам)")).toBeVisible();
  });

  it("«Загрузить письма за период»: ход и итог «загружено N»", async () => {
    const side = await mailPanel();
    fireEvent.click(await within(side).findByRole("button", { name: "Загрузить" }));
    expect(
      await within(side).findByText(/Загружено новых писем: 2 из 3/, {}, { timeout: 15000 }),
    ).toBeVisible();
    expect(within(side).getByText(/Повторная загрузка безопасна/)).toBeVisible();
  }, 20000);
});
