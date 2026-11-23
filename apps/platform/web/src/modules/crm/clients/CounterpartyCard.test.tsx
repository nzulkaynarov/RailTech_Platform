import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { resetMarks } from "../../../mocks/doNotWorkMarks";
import { resetLeads } from "../../../mocks/fixtures/leads";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { server } from "../../../test/server";

setupBotTests();

beforeEach(() => {
  resetLeads();
  resetMarks();
});

async function open(email: string, path: string) {
  signIn(email);
  renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: "Контрагенты" })).toBeVisible();
  return panelEl();
}

/** ADR-0028 (СУЩ-2.5): одна компания во всех ролях — одна карточка, роли — отметки. */
describe("Карточка контрагента", () => {
  it("клиент: шапка, роль «Клиент», вкладки; «Обзор» — люди и счета; заявки — та же карточка", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    const roles = within(panel).getByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Клиент")).toBeVisible();
    // менеджер роли не отмечает: «+ Поставщик» ему не предлагается
    expect(within(roles).queryByRole("button")).toBeNull();
    expect(within(panel).getByRole("tab", { name: "Заявки и проекты" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByRole("heading", { name: "Люди" })).toBeVisible();
    expect(within(panel).getByRole("heading", { name: "Банковские счета" })).toBeVisible();
    expect(within(panel).getByText("Счетов пока нет.")).toBeVisible();
  });

  it("поставщик: снабженец отмечает роль «Изготовитель» — новая карточка не нужна; занятую роль снять нельзя", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север»" }),
    ).toBeVisible();
    const roles = within(panel).getByRole("list", { name: "Роли" });
    const maker = within(roles).getByRole("button", { name: "+ Изготовитель" });
    expect(maker).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(maker);
    expect(await within(roles).findByRole("button", { name: "✓ Изготовитель" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(within(roles).getByRole("button", { name: "✓ Поставщик" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "Роль занята: у компании есть предложения или бренды.",
    );

    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByText("АКБ «Демо Банк»")).toBeVisible();
    // снабженцу номер счёта не показывается целиком
    expect(within(panel).getByText(/…0001/)).toBeVisible();
    expect(within(panel).getByText("Номера счетов видит бухгалтерия.")).toBeVisible();
  });

  it("одна компания — клиент, поставщик и изготовитель: три вкладки и бренды в «Обзоре»", async () => {
    server.use(
      http.get("*/people/clients/3/counterparty", () =>
        HttpResponse.json({
          id: "1",
          name: "ООО Рельс-Сервис Демо",
          inn: "300000003",
          registration_number: null,
          country: "Узбекистан",
          legal_address: "г. Ташкент, ул. Демо, 1",
          crm_client_id: 3,
          roles: {
            client: true,
            supplier: true,
            manufacturer: true,
            partner: true,
            organization: false,
          },
          people: [],
          bank_accounts: [],
          accounts_masked: false,
          brands: [{ id: "5", name: "PL-Rail" }],
        }),
      ),
    );
    const panel = await open("director@demo.example", "/crm/clients/3?panel=open&tab=card");
    const roles = await within(panel).findByRole("list", { name: "Роли" });
    expect(within(roles).getByText("Партнёр с кабинетом")).toBeVisible();
    for (const name of ["Обзор", "Заявки и проекты", "Товары поставщика"]) {
      expect(within(panel).getByRole("tab", { name })).toBeVisible();
    }
    fireEvent.click(within(panel).getByRole("tab", { name: "Обзор" }));
    expect(await within(panel).findByRole("heading", { name: "Как изготовитель" })).toBeVisible();
    expect(within(panel).getByText("PL-Rail")).toBeVisible();
  });

  it("клиент ещё не передан в ERP: прежняя карточка клиента, без ролей и вкладок", async () => {
    server.use(
      http.get("*/people/clients/3/counterparty", () =>
        HttpResponse.json({ code: "NOT_FOUND", message: "x", source: "erp" }, { status: 404 }),
      ),
    );
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    await waitFor(() => {
      expect(within(panel).queryByRole("tab", { name: "Обзор" })).toBeNull();
    });
  });

  it("реквизиты правятся в карточке (СУЩ-2.7): название и адрес — новые в шапке; дубль ИНН — понятный отказ", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север»" }),
    ).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Реквизиты" }));
    const sheet = await screen.findByRole("dialog", { name: "Реквизиты контрагента" });
    expect(within(sheet).getByRole("button", { name: "Сохранить" })).toBeDisabled();
    fireEvent.change(within(sheet).getByLabelText("Название"), {
      target: { value: "ООО «Поставщик Север-2»" },
    });
    fireEvent.change(within(sheet).getByLabelText("Юридический адрес"), {
      target: { value: "Ташкент, ул. Новая, 5" },
    });
    fireEvent.click(within(sheet).getByRole("button", { name: "Сохранить" }));
    expect(
      await within(panel).findByRole("heading", { name: "ООО «Поставщик Север-2»" }),
    ).toBeVisible();
    expect(within(panel).getByText(/Ташкент, ул\. Новая, 5/)).toBeVisible();

    server.use(
      http.patch("*/people/counterparties/:id", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "x", source: "erp", details: { reason: "company_exists" } },
          { status: 409 },
        ),
      ),
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Реквизиты" }));
    const again = await screen.findByRole("dialog", { name: "Реквизиты контрагента" });
    fireEvent.change(within(again).getByLabelText("ИНН"), { target: { value: "300000999" } });
    fireEvent.click(within(again).getByRole("button", { name: "Сохранить" }));
    expect(
      await within(again).findByText("Такой ИНН или рег. номер уже у другой компании."),
    ).toBeVisible();
  });

  it("бухгалтер реквизиты не правит: кнопки нет", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("button", { name: "Реквизиты" })).toBeNull();
  });
});

/** Х-8: «Не работать» — факты у компании; полоса в карточке, «Снова работать» снимает. */
describe("Карточка контрагента: «Не работать»", () => {
  it("снабженец отмечает компанию с причиной; полоса показывает причину и кто отметил; «Снова работать» снимает", async () => {
    const panel = await open("supply@demo.example", "/crm/clients?partner=1&panel=open&tab=card");
    await within(panel).findByRole("heading", { name: /Поставщик Север/ });
    expect(within(panel).queryByRole("status")).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Не работать" }));
    const dialog = await screen.findByRole("dialog", { name: "С компанией не работаем" });
    const submit = within(dialog).getByRole("button", { name: "Отметить" });
    // без причины отметить нельзя
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Дважды не оплатил отгрузку" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    const strip = await within(panel).findByRole("status");
    expect(strip).toHaveTextContent("С компанией не работаем: Дважды не оплатил отгрузку");
    expect(strip).toHaveTextContent("Отметил:");
    expect(within(panel).queryByRole("button", { name: "Не работать" })).toBeNull();

    fireEvent.click(within(panel).getByRole("button", { name: "Снова работать" }));
    await waitFor(() => {
      expect(within(panel).queryByRole("status")).toBeNull();
    });
    expect(await within(panel).findByRole("button", { name: "Не работать" })).toBeVisible();
  });

  it("менеджер клиентов отмечает клиента — отметка видна в списке («Не работаем») и в строке клиента", async () => {
    const panel = await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    fireEvent.click(within(panel).getByRole("button", { name: "Не работать" }));
    const dialog = await screen.findByRole("dialog", { name: "С компанией не работаем" });
    fireEvent.change(within(dialog).getByLabelText("Причина"), {
      target: { value: "Спор по оплате" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отметить" }));
    expect(await within(panel).findByRole("status")).toHaveTextContent("Спор по оплате");
  });

  it("бухгалтер отметку видит, но поставить её не может", async () => {
    const panel = await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("button", { name: "Не работать" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Реквизиты" })).toBeNull();
  });
});
