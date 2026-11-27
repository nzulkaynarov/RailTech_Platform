import { fireEvent, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  findPartnerCard,
  partnerPath,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";
import { server } from "../../../test/server";

setupCatalogTests();

async function openSupplier(email: string, id: string, name: string): Promise<HTMLElement> {
  signIn(email);
  renderAt(partnerPath(id));
  const drawer = await findPartnerCard(name);
  await within(drawer).findByRole("heading", { name: "Доступ в кабинет" });
  return drawer;
}

async function block(drawer: HTMLElement): Promise<HTMLElement> {
  const region = (await within(drawer).findByRole("heading", { name: "Доступ в кабинет" })).closest(
    "section",
  );
  if (!region) throw new Error("нет блока «Доступ в кабинет»");
  return region;
}

describe("Партнёр: блок «Доступ в кабинет»", () => {
  it("кабинет не открывали: статус, подсказка, «Мои товары» включён, раздел покупателя нет (ДК-5), роли пусты", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);

    expect(await within(section).findByText("Не открыт")).toBeVisible();
    expect(within(section).getByText("Кабинет закрыт: партнёр войти не может.")).toBeVisible();
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).toBeChecked();
    const catalog = within(section).getByRole("switch", { name: /Каталог и заявки/ });
    expect(catalog).not.toBeChecked();
    expect(
      within(section).getByText(
        "Каталог — как у клиентов: опубликованные товары и цены, без партнёров.",
      ),
    ).toBeVisible();
    expect(within(section).getByText("Азиз Тошматов")).toBeVisible();
    expect(within(section).queryByRole("button", { name: "Приостановить доступ" })).toBeNull();
  });

  it("добавить контакт: ФИО, e-mail, телефон, язык — и он в списке", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Добавить контакт" }));

    const form = await findModal("Новый контакт партнёра");
    expect(within(form).getByRole("button", { name: "Добавить" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Нодира Рахимова" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "nodira@sever-supply.example" },
    });
    fireEvent.change(within(form).getByLabelText("Телефон"), {
      target: { value: "+998 90 000 00 02" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await modalClosed("Новый контакт партнёра");

    expect(await within(section).findByText("Нодира Рахимова")).toBeVisible();
    expect(within(section).getByText("nodira@sever-supply.example")).toBeVisible();
  });

  it("право контакта действовать: у заведённого в карточке выключено, включается; в форме нового — включено", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    const aziz = await within(section).findByRole("switch", {
      name: "Может подтверждать: Азиз Тошматов",
    });
    expect(aziz).not.toBeChecked();
    fireEvent.click(aziz);
    await waitFor(() => {
      expect(
        within(section).getByRole("switch", {
          name: "Может подтверждать: Азиз Тошматов",
        }),
      ).toBeChecked();
    });

    fireEvent.click(within(section).getByRole("button", { name: "Добавить контакт" }));
    const form = await findModal("Новый контакт партнёра");
    const canAct = within(form).getByRole("switch");
    expect(canAct).toBeChecked();
    fireEvent.click(canAct);
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Нодира Рахимова" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "nodira@sever-supply.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await modalClosed("Новый контакт партнёра");
    expect(
      await within(section).findByRole("switch", {
        name: "Может подтверждать: Нодира Рахимова",
      }),
    ).not.toBeChecked();
  });

  it("повторный адрес — ошибка словами, окно остаётся", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Добавить контакт" }));
    const form = await findModal("Новый контакт партнёра");
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Дубль" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "aziz@sever-supply.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(/уже есть/);
  });

  it("пригласить контакт без права: право выбирает приглашающий, по умолчанию включено (ДК-5)", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    const right = within(section).getByRole("switch", {
      name: "Может подтверждать: Азиз Тошматов",
    });
    expect(right).not.toBeChecked();
    fireEvent.click(
      await within(section).findByRole("button", { name: "Пригласить: Азиз Тошматов" }),
    );
    const ask = await findModal("Пригласить в кабинет");
    expect(within(ask).getByRole("switch", { name: "Может подтверждать" })).toBeChecked();
    fireEvent.click(within(ask).getByRole("button", { name: "Пригласить" }));
    await modalClosed("Пригласить в кабинет");
    expect(await within(section).findByText("Приглашён")).toBeVisible();
    await waitFor(() => {
      expect(
        within(section).getByRole("switch", { name: "Может подтверждать: Азиз Тошматов" }),
      ).toBeChecked();
    });
  });

  it("пригласить: отношение «Приглашён», в кабинете «Партнёр», у контакта «Пригласить ещё раз»", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(
      await within(section).findByRole("switch", { name: "Может подтверждать: Азиз Тошматов" }),
    );
    await waitFor(() => {
      expect(
        within(section).getByRole("switch", { name: "Может подтверждать: Азиз Тошматов" }),
      ).toBeChecked();
    });
    fireEvent.click(
      await within(section).findByRole("button", { name: "Пригласить: Азиз Тошматов" }),
    );

    expect(await within(section).findByText("Приглашён")).toBeVisible();
    expect(within(section).getByText("В кабинете: Партнёр")).toBeVisible();
    expect(within(section).getByText("Письмо с кодом входа отправлено.")).toBeVisible();
    expect(
      within(section).getByRole("button", { name: "Пригласить ещё раз: Азиз Тошматов" }),
    ).toHaveTextContent("Пригласить ещё раз");
    expect(within(section).getByRole("button", { name: "Приостановить доступ" })).toBeVisible();
  });

  it("выбор разделов до приглашения уходит с приглашением; потом переключатель правит сразу", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("switch", { name: /Мои товары/ }));
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).not.toBeChecked();
    fireEvent.click(within(section).getByRole("button", { name: "Пригласить: Азиз Тошматов" }));
    fireEvent.click(
      within(await findModal("Пригласить в кабинет")).getByRole("button", { name: "Пригласить" }),
    );
    await within(section).findByText("Приглашён");
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).not.toBeChecked();
    expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();

    fireEvent.click(within(section).getByRole("switch", { name: /Мои товары/ }));
    await waitFor(() => {
      expect(within(section).getByRole("switch", { name: /Мои товары/ })).toBeChecked();
    });
  });

  it("клиент и партнёр: роли показаны вместе", async () => {
    const drawer = await openSupplier("supply@demo.example", "2", "АО «Южный Металл»");
    const section = await block(drawer);
    expect(await within(section).findByText("Активен")).toBeVisible();
    expect(within(section).getByText("В кабинете: Клиент · Партнёр")).toBeVisible();
    expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();
  });

  it("КОНТР-1б: вошёл клиентом, партнёрского отношения нет — «Открыт», последний вход и что видит; не «Не открыт»", async () => {
    server.use(
      http.get("*/erp/catalog/suppliers/1/cabinet-access", () =>
        HttpResponse.json({
          company_id: "1",
          company_name: "ООО «Поставщик Север»",
          crm_client: { status: "none", crm_client_id: null },
          relationship: null,
          contacts: [
            {
              id: "501",
              name: "Азиз Тошматов",
              email: "aziz@sever-supply.example",
              phone: "",
              language: "ru",
              can_act: true,
              invited_at: "2026-11-25T07:00:00+05:00",
              last_login_at: "2026-11-25T13:22:00+05:00",
            },
          ],
          partner_modules: {
            allowed: ["my_products", "catalog_requests"],
            default: ["my_products"],
          },
          cabinet_roles: ["client"],
          cabinet_modules: ["quotes"],
          cabinet: {
            opened: true,
            roles: ["client"],
            sees: "client",
            last_login_at: "2026-11-25T13:22:00+05:00",
            logged_in_contacts: 1,
          },
          can_manage: true,
        }),
      ),
    );
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    expect(await within(section).findByText("Открыт")).toBeVisible();
    expect(within(section).queryByText("Не открыт")).toBeNull();
    expect(within(section).queryByText(/ещё не открывали/)).toBeNull();
    expect(within(section).getByText("Раздел клиента")).toBeVisible();
    expect(within(section).getByText("Последний вход")).toBeVisible();
    expect(within(section).getByText("В кабинете: Клиент")).toBeVisible();
  });

  it("приостановить: подтверждение «Что произойдёт», затем статус «Приостановлен» и закрытый кабинет", async () => {
    const drawer = await openSupplier("supply@demo.example", "2", "АО «Южный Металл»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Приостановить доступ" }));

    const confirm = await findModal("Приостановить доступ в кабинет");
    fireEvent.click(within(confirm).getByRole("button", { name: "Приостановить" }));
    await modalClosed("Приостановить доступ в кабинет");

    expect((await within(section).findAllByText("Приостановлен")).length).toBeGreaterThan(0);
    expect(within(section).getByText("В кабинете: Клиент")).toBeVisible(); // клиентская роль осталась
    expect(within(section).queryByRole("button", { name: "Приостановить доступ" })).toBeNull();
    expect(
      within(section).getByRole("button", { name: "Пригласить ещё раз: Малика Юсупова" }),
    ).toHaveTextContent("Пригласить ещё раз");
  });

  it("менеджер видит состояние, но не меняет: кнопок и переключателей нет", async () => {
    const drawer = await openSupplier("manager@demo.example", "2", "АО «Южный Металл»");
    const section = await block(drawer);
    expect(await within(section).findByText("Активен")).toBeVisible();
    for (const name of ["Добавить контакт", "Приостановить доступ"]) {
      expect(within(section).queryByRole("button", { name })).toBeNull();
    }
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).toBeDisabled();
    expect(within(section).getByRole("switch", { name: /Может подтверждать/ })).toBeDisabled();
  });
});
