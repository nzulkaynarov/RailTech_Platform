import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

async function openApplications(email: string) {
  signIn(email);
  const view = renderAt("/erp/catalog?part=applications");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Номенклатура и поставщики" }),
  ).toBeVisible();
  expect(await screen.findByText("ООО «Сталь-Транс»")).toBeVisible();
  return view;
}

describe("Очередь заявок кандидатов в партнёры (PART-ONBOARD-2)", () => {
  it("отображает заявки со статусами, совпадением по ИНН и фильтрами", async () => {
    await openApplications("supply@demo.example");

    // Проверяем элементы таблицы
    expect(screen.getByText("ООО «Сталь-Транс»")).toBeVisible();
    expect(screen.getByText("ИНН: 7701999888")).toBeVisible();
    expect(screen.getByText("Совпадение в базе: АО «Южный Металл»")).toBeVisible();
    expect(screen.getByText("Сергей Кузнецов")).toBeVisible();
    expect(screen.getByText("kuznetsov@stal-trans.example")).toBeVisible();
    expect(screen.getByText("Подана")).toBeVisible();

    // Вторая заявка
    const vostokRow = screen.getByText("ООО «Восток Снаб»").closest("tr");
    expect(vostokRow).not.toBeNull();
    if (!vostokRow) throw new Error("Row not found");
    expect(within(vostokRow).getByText("Договор отправлен")).toBeVisible();
    expect(within(vostokRow).getByText("№ ПД-2026/102")).toBeVisible();

    // Фильтр по статусу «Новые»
    fireEvent.click(screen.getByRole("button", { name: "Новые" }));
    expect(screen.getByText("ООО «Сталь-Транс»")).toBeVisible();
    expect(screen.queryByText("ООО «Восток Снаб»")).toBeNull();

    // Фильтр по «Все заявки»
    fireEvent.click(screen.getByRole("button", { name: "Все заявки" }));
    expect(screen.getByText("ООО «Восток Снаб»")).toBeVisible();
  });

  it("снабжение может отправить проект договора кандидату", async () => {
    await openApplications("supply@demo.example");

    fireEvent.click(screen.getByRole("button", { name: "Отправить договор" }));
    const modal = await findModal(/Отправка проекта договора/);

    fireEvent.change(within(modal).getByLabelText("Номер договора"), {
      target: { value: "ПД-2026/777" },
    });
    fireEvent.change(within(modal).getByLabelText("Дата договора"), {
      target: { value: "2026-11-06" },
    });

    fireEvent.click(within(modal).getByRole("button", { name: "Отметить договор отправленным" }));
    await modalClosed(/Отправка проекта договора/);

    expect(await screen.findByText("№ ПД-2026/777")).toBeVisible();
  });

  it("снабжение может одобрить договор и открыть доступ", async () => {
    await openApplications("supply@demo.example");

    const [approveButton] = screen.getAllByRole("button", { name: "Одобрить и открыть кабинет" });
    if (!approveButton) throw new Error("No approve button found");
    fireEvent.click(approveButton);

    const modal = await findModal(/Одобрение заявки и открытие кабинета/);
    expect(
      within(modal).getByRole("radio", {
        name: /Привязать к найденной организации: АО «Южный Металл»/,
      }),
    ).toBeInTheDocument();

    fireEvent.change(within(modal).getByLabelText(/Номер договора/), {
      target: { value: "DOG-PART-FINAL" },
    });

    fireEvent.click(
      within(modal).getByRole("button", { name: "Подтвердить договор и открыть доступ" }),
    );
    await modalClosed(/Одобрение заявки и открытие кабинета/);

    expect(await screen.findByText("№ DOG-PART-FINAL")).toBeVisible();
    expect(await screen.findByText("Одобрена")).toBeVisible();
  });

  it("снабжение может отклонить заявку с указанием причины", async () => {
    await openApplications("supply@demo.example");

    const [rejectButton] = screen.getAllByRole("button", { name: "Отклонить" });
    if (!rejectButton) throw new Error("No reject button found");
    fireEvent.click(rejectButton);

    const modal = await findModal(/Отклонение заявки/);
    const okBtn = within(modal).getByRole("button", { name: "Отклонить заявку" });
    expect(okBtn).toBeDisabled();

    fireEvent.change(within(modal).getByLabelText(/Причина отклонения/), {
      target: { value: "Несоответствие профилю поставляемой продукции" },
    });
    expect(okBtn).not.toBeDisabled();

    fireEvent.click(okBtn);
    await modalClosed(/Отклонение заявки/);

    expect(await screen.findByText("Отклонена")).toBeVisible();
    expect(await screen.findByText("Несоответствие профилю поставляемой продукции")).toBeVisible();
  });

  it("сотрудник без прав не видит кнопок мутации", async () => {
    // Вход под бухгалтером (нет supply.manage / erp.stock write)
    signIn("accountant@demo.example");
    renderAt("/erp/catalog?part=applications");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Номенклатура и поставщики" }),
    ).toBeVisible();
    expect(await screen.findByText("ООО «Сталь-Транс»")).toBeVisible();

    expect(screen.queryByRole("button", { name: "Отправить договор" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Одобрить и открыть кабинет" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отклонить" })).toBeNull();
  });
});
