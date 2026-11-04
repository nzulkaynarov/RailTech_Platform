import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

async function openSupplier(email: string, id: string, name: string): Promise<HTMLElement> {
  signIn(email);
  renderAt(`/erp/catalog?part=suppliers&supplier=${id}`);
  const drawer = await screen.findByRole("dialog", { name });
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

describe("Поставщик: блок «Доступ в кабинет»", () => {
  it("кабинет не открывали: статус, подсказка, разделы по умолчанию включены, роли пусты", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);

    expect(await within(section).findByText("Не открыт")).toBeVisible();
    expect(within(section).getByText("Кабинет закрыт: партнёр войти не может.")).toBeVisible();
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).toBeChecked();
    const catalog = within(section).getByRole("switch", { name: /Каталог и заявки/ });
    expect(catalog).toBeChecked();
    expect(
      within(section).getByText(
        "Каталог — как у клиентов: опубликованные товары и цены, без поставщиков.",
      ),
    ).toBeVisible();
    expect(within(section).getByText("Азиз Тошматов")).toBeVisible();
    expect(within(section).queryByRole("button", { name: "Приостановить доступ" })).toBeNull();
  });

  it("добавить контакт: ФИО, e-mail, телефон, язык — и он в списке", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Добавить контакт" }));

    const form = await findModal("Новый контакт поставщика");
    expect(within(form).getByRole("button", { name: "Добавить" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Нодира Рахимова" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "nodira@sever-supply.example" },
    });
    fireEvent.change(within(form).getByLabelText("Телефон"), {
      target: { value: "+998 90 000 00 02" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await modalClosed("Новый контакт поставщика");

    expect(await within(section).findByText("Нодира Рахимова")).toBeVisible();
    expect(within(section).getByText("nodira@sever-supply.example")).toBeVisible();
  });

  it("право контакта действовать: по умолчанию включено, выключается у контакта и в форме", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    const aziz = await within(section).findByRole("switch", {
      name: "Может создавать запросы и загружать файлы: Азиз Тошматов",
    });
    expect(aziz).toBeChecked();
    fireEvent.click(aziz);
    await waitFor(() => {
      expect(
        within(section).getByRole("switch", {
          name: "Может создавать запросы и загружать файлы: Азиз Тошматов",
        }),
      ).not.toBeChecked();
    });

    fireEvent.click(within(section).getByRole("button", { name: "Добавить контакт" }));
    const form = await findModal("Новый контакт поставщика");
    const canAct = within(form).getByRole("switch");
    expect(canAct).toBeChecked();
    fireEvent.click(canAct);
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Нодира Рахимова" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "nodira@sever-supply.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await modalClosed("Новый контакт поставщика");
    expect(
      await within(section).findByRole("switch", {
        name: "Может создавать запросы и загружать файлы: Нодира Рахимова",
      }),
    ).not.toBeChecked();
  });

  it("повторный адрес — ошибка словами, окно остаётся", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Добавить контакт" }));
    const form = await findModal("Новый контакт поставщика");
    fireEvent.change(within(form).getByLabelText("ФИО"), { target: { value: "Дубль" } });
    fireEvent.change(within(form).getByLabelText("E-mail"), {
      target: { value: "aziz@sever-supply.example" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(/уже есть/);
  });

  it("пригласить: отношение «Приглашён», в кабинете «Партнёр», у контакта «Пригласить ещё раз»", async () => {
    const drawer = await openSupplier("supply@demo.example", "1", "ООО «Поставщик Север»");
    const section = await block(drawer);
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
    fireEvent.click(await within(section).findByRole("switch", { name: /Каталог и заявки/ }));
    expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();
    fireEvent.click(within(section).getByRole("button", { name: "Пригласить: Азиз Тошматов" }));
    await within(section).findByText("Приглашён");
    expect(within(section).getByRole("switch", { name: /Мои товары/ })).toBeChecked();
    expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();

    fireEvent.click(within(section).getByRole("switch", { name: /Каталог и заявки/ }));
    await waitFor(() => {
      expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).toBeChecked();
    });
  });

  it("клиент и партнёр: роли показаны вместе", async () => {
    const drawer = await openSupplier("supply@demo.example", "2", "АО «Южный Металл»");
    const section = await block(drawer);
    expect(await within(section).findByText("Активен")).toBeVisible();
    expect(within(section).getByText("В кабинете: Клиент · Партнёр")).toBeVisible();
    expect(within(section).getByRole("switch", { name: /Каталог и заявки/ })).not.toBeChecked();
  });

  it("приостановить: подтверждение «Что произойдёт», затем статус «Приостановлен» и закрытый кабинет", async () => {
    const drawer = await openSupplier("supply@demo.example", "2", "АО «Южный Металл»");
    const section = await block(drawer);
    fireEvent.click(await within(section).findByRole("button", { name: "Приостановить доступ" }));

    const confirm = await findModal("Приостановить доступ в кабинет");
    expect(within(confirm).getByText(/Открытые сессии партнёра закроются/)).toBeInTheDocument();
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
    expect(
      within(section).getByRole("switch", { name: /Может создавать запросы и загружать файлы/ }),
    ).toBeDisabled();
  });
});
