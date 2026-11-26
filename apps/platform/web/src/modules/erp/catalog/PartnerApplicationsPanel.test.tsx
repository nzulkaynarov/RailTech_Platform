import { fireEvent, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";
import { server } from "../../../test/server";

setupCatalogTests();

async function openApplications(email: string) {
  signIn(email);
  const view = renderAt("/crm/clients?kind=applications");
  expect(await screen.findByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
  expect(await screen.findByText("ООО «Сталь-Транс»")).toBeVisible();
  return view;
}

describe("Очередь заявок кандидатов в партнёры (PART-ONBOARD-2)", () => {
  it("заявка из карточки лида подписана источником «Лид» и номером лида (ЛП-1)", async () => {
    server.use(
      http.get("*/erp/catalog/partner-applications", () =>
        HttpResponse.json({
          pending_count: 1,
          items: [
            {
              id: "301",
              source: "lead",
              source_ref: "L-2041",
              status: "submitted",
              kind: "supplier",
              company_name: "ООО «Лид-Партнёр»",
              inn: "",
              contact_name: "Олим Лидов",
              email: "olim@lead-partner.example",
              phone: "",
              language: "ru",
              categories_description: "Крепёж",
              contract_number: "",
              contract_date: null,
              rejected_reason: "",
              created_at: "2026-11-25T09:30:00+05:00",
              reviewed_at: null,
              matching_company_id: null,
              matching_company_name: null,
              company_match_pending: null,
              invite_delivery: null,
            },
          ],
        }),
      ),
    );
    signIn("supply@demo.example");
    renderAt("/crm/clients?kind=applications");
    const row = (await screen.findByText("ООО «Лид-Партнёр»")).closest("tr");
    if (!row) throw new Error("Row not found");
    expect(within(row).getByText("Лид")).toBeVisible();
  });

  it("отображает заявки со статусами, совпадением по ИНН и фильтрами", async () => {
    await openApplications("supply@demo.example");

    // Проверяем элементы таблицы
    expect(screen.getByText("ООО «Сталь-Транс»")).toBeVisible();
    expect(screen.getByText("ИНН: 7701999888")).toBeVisible();
    expect(screen.getByText("Совпадение в базе: АО «Южный Металл»")).toBeVisible();
    expect(screen.getByText("Сергей Кузнецов")).toBeVisible();
    expect(screen.getByText("kuznetsov@stal-trans.example")).toBeVisible();
    expect(screen.getAllByText("Подана")[0]).toBeVisible();

    // Вторая заявка
    const vostokRow = screen.getByText("ООО «Восток Снаб»").closest("tr");
    expect(vostokRow).not.toBeNull();
    if (!vostokRow) throw new Error("Row not found");
    expect(within(vostokRow).getByText("Договор отправлен")).toBeVisible();
    expect(within(vostokRow).getByText("№ ПД-2026/102")).toBeVisible();

    // Фильтр по статусу «Новые»
    fireEvent.click(screen.getByText("Новые", { selector: ".ant-segmented-item-label" }));
    expect(screen.getByText("ООО «Сталь-Транс»")).toBeVisible();
    expect(screen.queryByText("ООО «Восток Снаб»")).toBeNull();

    // Фильтр по «Все заявки»
    fireEvent.click(screen.getByText("Все заявки", { selector: ".ant-segmented-item-label" }));
    expect(screen.getByText("ООО «Восток Снаб»")).toBeVisible();
  });

  it("снабжение отправляет подготовленный договор кандидату", async () => {
    await openApplications("supply@demo.example");

    fireEvent.click(screen.getByRole("button", { name: "Отправить договор" }));
    const modal = await findModal(/Отправка договора/);

    // FX-1: совпадение по ИНН — вопрос сотруднику, без ответа договор не уходит
    const okBtn = within(modal).getByRole("button", { name: "Отправить договор" });
    expect(within(modal).getByText(/Это та же компания\?/)).toBeInTheDocument();
    expect(within(modal).queryByRole("radio", { name: /Создать новую/ })).toBeNull();
    expect(okBtn).toBeDisabled();
    fireEvent.click(
      within(modal).getByRole("radio", {
        name: /Привязать к найденной организации: АО «Южный Металл»/,
      }),
    );
    expect(okBtn).not.toBeDisabled();
    // ПД-1: номер и дата заданы при подготовке договора, здесь их не вводят
    expect(within(modal).queryByLabelText("Номер договора")).toBeNull();

    fireEvent.click(okBtn);
    await modalClosed(/Отправка договора/);

    expect(await screen.findAllByText("Ждём ответа кандидата")).not.toHaveLength(0);
  });

  it("согласованную кандидатом заявку одобряют без причины", async () => {
    await openApplications("supply@demo.example");

    expect(screen.getByText("Согласован кандидатом")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Отметить: подписан" }));

    const modal = await findModal(/Договор подписан/);
    expect(within(modal).queryByLabelText(/Причина одобрения без согласия/)).toBeNull();

    fireEvent.change(within(modal).getByLabelText(/Номер договора/), {
      target: { value: "DOG-PART-FINAL" },
    });
    fireEvent.click(
      within(modal).getByRole("button", { name: "Отметить: подписан" }),
    );
    await modalClosed(/Договор подписан/);

    expect(await screen.findByText("№ DOG-PART-FINAL")).toBeVisible();
    expect(await screen.findByText("Одобрена")).toBeVisible();
  });

  it("без согласия кандидата одобрить можно только с причиной", async () => {
    await openApplications("supply@demo.example");

    const vostokRow = screen.getByText("ООО «Восток Снаб»").closest("tr");
    if (!vostokRow) throw new Error("Row not found");
    expect(
      within(vostokRow).queryByRole("button", { name: "Отметить: подписан" }),
    ).toBeNull();
    fireEvent.click(within(vostokRow).getByRole("button", { name: "Отметить: подписан без согласия" }));

    const modal = await findModal(/Договор подписан/);
    const okBtn = within(modal).getByRole("button", {
      name: "Отметить: подписан",
    });
    expect(okBtn).toBeDisabled();

    fireEvent.change(within(modal).getByLabelText(/Причина одобрения без согласия/), {
      target: { value: "Договор подписан на бумаге" },
    });
    fireEvent.change(within(modal).getByLabelText("Заметка вместо скана"), {
      target: { value: "Подписан на встрече" },
    });
    expect(okBtn).not.toBeDisabled();

    fireEvent.click(okBtn);
    await modalClosed(/Договор подписан/);
    expect(await screen.findByText("Одобрена")).toBeVisible();
  });

  it("новую заявку нельзя одобрить, пока не отправлен договор", async () => {
    await openApplications("supply@demo.example");

    const newRow = screen.getByText("ООО «Сталь-Транс»").closest("tr");
    if (!newRow) throw new Error("Row not found");
    expect(within(newRow).queryByRole("button", { name: "Отметить: подписан без согласия" })).toBeNull();
    expect(within(newRow).queryByRole("button", { name: "Отметить: подписан" })).toBeNull();
  });

  it("сбой письма виден в строке, договор можно отправить снова", async () => {
    await openApplications("supply@demo.example");

    const vostokRow = screen.getByText("ООО «Восток Снаб»").closest("tr");
    if (!vostokRow) throw new Error("Row not found");
    expect(within(vostokRow).getByText("Письмо-приглашение не доставлено")).toBeVisible();
    expect(
      within(vostokRow).getByRole("button", { name: "Отправить договор снова" }),
    ).toBeVisible();
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
    renderAt("/crm/clients?kind=applications");

    expect(await screen.findByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
    expect(await screen.findByText("ООО «Сталь-Транс»")).toBeVisible();

    expect(screen.queryByRole("button", { name: "Отправить договор" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отметить: подписан" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отклонить" })).toBeNull();
  });
});
