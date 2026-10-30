import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { listSettled } from "../../../test/settled";

setupCalcTests();

const ORDER = `ЗП-${String(new Date().getFullYear())}-029`;
const ORDER_PATH = `/erp/stock/${encodeURIComponent(ORDER)}`;

async function openStock(email: string, view = "") {
  signIn(email);
  renderAt(`/erp/stock${view ? `?view=${view}` : ""}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
}

async function rowOf(text: string): Promise<HTMLElement> {
  const cell = (await screen.findAllByText(text))[0];
  const tr = cell?.closest("tr");
  if (!tr) throw new Error(`нет строки ${text}`);
  return tr;
}

describe("Склад · остатки и резервы", () => {
  it("снабженец видит остаток, резерв, свободное, ожидаемый приход и ячейки", async () => {
    await openStock("supply@demo.example");
    const drive = within(
      await screen.findByRole("table", { name: "Остатки и резервы по номенклатуре" }),
    );
    const row = within(
      drive
        .getAllByText("Привод стрелочный электромеханический СП-6М")[0]
        ?.closest("tr") as HTMLElement,
    );
    expect(row.getByText("Свободно · 6")).toBeVisible();
    expect(row.getByText("B-04-1: 4 · B-04-2: 2")).toBeVisible();
    const fasteners = within(
      drive.getAllByText("Скрепление рельсовое КБ-65")[0]?.closest("tr") as HTMLElement,
    );
    expect(fasteners.getByText("Свободно · 30")).toBeVisible();
    expect(fasteners.getByText("+30")).toBeVisible();
  });

  it("«Только с резервом» оставляет товары с резервом проекта", async () => {
    await openStock("supply@demo.example");
    await screen.findByRole("table", { name: "Остатки и резервы по номенклатуре" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Только с резервом" }));
    await listSettled();
    expect(await screen.findByText("Скрепление рельсовое КБ-65")).toBeVisible();
    expect(
      screen.queryByText("Привод стрелочный электромеханический СП-6М"),
    ).not.toBeInTheDocument();
  });

  it("карточка товара: резервы по проектам, ожидаемый приход; оприходовать растит остаток", async () => {
    await openStock("supply@demo.example");
    fireEvent.click(
      await screen.findByRole("button", { name: "Открыть товар «Скрепление рельсовое КБ-65»" }),
    );
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByRole("link", { name: "ПР-2026-099" })).toBeVisible();
    expect(within(drawer).getByRole("link", { name: ORDER })).toBeVisible();
    fireEvent.click(within(drawer).getByRole("button", { name: "Оприходовать или списать" }));
    const modal = (await screen.findAllByRole("dialog")).at(-1) as HTMLElement;
    fireEvent.change(within(modal).getByRole("spinbutton", { name: /Количество/ }), {
      target: { value: "5" },
    });
    fireEvent.change(within(modal).getByRole("textbox", { name: /Ячейка/ }), {
      target: { value: "C-01-1" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Записать" }));
    expect(await screen.findByText("Остаток изменён")).toBeVisible();
    await waitFor(() => {
      expect(
        within(screen.getAllByRole("dialog")[0] as HTMLElement).getAllByText("55").length,
      ).toBeGreaterThan(0);
    });
  });

  it("менеджер читает склад, но «Оприходовать» и «Создать заказ» ему недоступны", async () => {
    await openStock("manager@demo.example");
    fireEvent.click(
      await screen.findByRole("button", { name: "Открыть товар «Скрепление рельсовое КБ-65»" }),
    );
    const drawer = await screen.findByRole("dialog");
    await within(drawer).findByRole("link", { name: "ПР-2026-099" });
    expect(
      within(drawer).queryByRole("button", { name: "Оприходовать или списать" }),
    ).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole("button", { name: /Снять резерв под/ }),
    ).not.toBeInTheDocument();
  });

  it("роль без раздела «Склад» получает экран «нет доступа»", async () => {
    signIn("admin@demo.example");
    renderAt("/erp/stock");
    const denied = await screen.findByText(/нет доступа|Нет доступа|не положен/i);
    // Администратору рабочая область видна после ответа чек-листа настройки (UX-1c, S10)
    await waitFor(() => {
      expect(denied).toBeVisible();
    });
    expect(screen.queryByRole("heading", { level: 1, name: "Склад" })).not.toBeInTheDocument();
  });
});

describe("Склад · заказы поставщикам", () => {
  it("список: ЗП-номер, поставщик, ожидаемая дата и просрочка, статус, приёмка, сумма", async () => {
    await openStock("supply@demo.example", "orders");
    const table = within(await screen.findByRole("table", { name: "Заказы поставщикам" }));
    const row = within(await rowOf(ORDER));
    expect(row.getByText("ООО «Вымышленная Сталь»")).toBeVisible();
    expect(row.getByText("Подтверждён")).toBeVisible();
    expect(row.getByText("Просрочен · 3 дн.")).toBeVisible();
    expect(row.getByText("0 из 30")).toBeVisible();
    expect(table.getByRole("columnheader", { name: "Сумма" })).toBeVisible();
    expect(row.getByText(/5\s?550\s?000/)).toBeVisible();
  });

  it("цены поставщиков скрыты от роли без них: нет колонки «Сумма»", async () => {
    await openStock("engineer@demo.example", "orders");
    const table = within(await screen.findByRole("table", { name: "Заказы поставщикам" }));
    expect(table.queryByRole("columnheader", { name: "Сумма" })).not.toBeInTheDocument();
    expect(screen.queryByText(/5\s?550\s?000/)).not.toBeInTheDocument();
  });

  it("карточка просроченного заказа: предупреждение, состав, «Принять товар» частично и полностью", async () => {
    signIn("supply@demo.example");
    renderAt(ORDER_PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ поставщику ${ORDER}` }),
    ).toBeVisible();
    expect(screen.getByText(/просрочка 3 дн\./)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Принять товар" }));
    let modal = await screen.findByRole("dialog");
    fireEvent.change(await within(modal).findByRole("spinbutton", { name: /Принять/ }), {
      target: { value: "10" },
    });
    fireEvent.change(within(modal).getByRole("textbox", { name: /Ячейка для/ }), {
      target: { value: "C-02-1" },
    });
    fireEvent.change(within(modal).getByRole("textbox", { name: "Накладная поставщика" }), {
      target: { value: "НП-77" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    expect(await screen.findByText("Товар принят")).toBeVisible();
    expect((await screen.findAllByText(/накладная НП-77/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Подтверждён").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Принять товар" }));
    modal = await screen.findByRole("dialog");
    expect(await within(modal).findByText("осталось 20 из 30")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Принять товар" })).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("Получен").length).toBeGreaterThan(0);
  });

  it("новый заказ: черновик → отправлен (письмо в журнале) → подтверждён; недопустимые кнопки не показываются", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("button", { name: "Создать заказ" }));
    const modal = await screen.findByRole("dialog");
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Поставщик" }));
    fireEvent.click(
      await screen.findByText("ООО «Вымышленная Сталь»", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Товар, строка 1" }));
    fireEvent.change(within(modal).getByRole("combobox", { name: "Товар, строка 1" }), {
      target: { value: "перевод" },
    });
    fireEvent.click(
      await screen.findByText(/Перевод стрелочный Р65 марки 1\/11/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.change(within(modal).getByRole("spinbutton", { name: "Количество, строка 1" }), {
      target: { value: "4" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Создать черновик" }));

    const year = String(new Date().getFullYear());
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ поставщику ЗП-${year}-030` }),
    ).toBeVisible();
    expect(screen.getAllByText("Черновик").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Принять товар" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Поставщик подтвердил" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отправить поставщику" }));
    const send = await screen.findByRole("dialog");
    expect(within(send).getByText("Что произойдёт")).toBeInTheDocument();
    fireEvent.click(within(send).getByRole("button", { name: "Отправить письмо" }));
    expect(await screen.findByText("Заказ отправлен поставщику")).toBeVisible();
    await screen.findByRole("button", { name: "Поставщик подтвердил" });
    expect(screen.getAllByText(/sales@steel\.example/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Поставщик подтвердил" }));
    const confirm = await screen.findByRole("dialog");
    const submit = within(confirm).getByRole("button", { name: "Подтвердить" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(confirm).getByLabelText("Подтверждённая дата поставки"), {
      target: { value: "2099-01-15" },
    });
    fireEvent.click(submit);
    expect(await screen.findByText("Заказ подтверждён")).toBeVisible();
    await screen.findByRole("button", { name: "Принять товар" });
    expect(screen.queryByRole("button", { name: "Отправить поставщику" })).not.toBeInTheDocument();
  });

  it("поставщик без почты: отправка требует адрес", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("button", { name: "Создать заказ" }));
    const modal = await screen.findByRole("dialog");
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Поставщик" }));
    fireEvent.click(
      await screen.findByText(/ООО «Пример Лес» · нет почты/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Товар, строка 1" }));
    fireEvent.change(within(modal).getByRole("combobox", { name: "Товар, строка 1" }), {
      target: { value: "брус" },
    });
    fireEvent.click(
      await screen.findByText(/Брус переводной/, { selector: ".ant-select-item-option-content" }),
    );
    fireEvent.change(within(modal).getByRole("spinbutton", { name: "Количество, строка 1" }), {
      target: { value: "2" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Создать черновик" }));
    await screen.findByRole("button", { name: "Отправить поставщику" });
    fireEvent.click(screen.getByRole("button", { name: "Отправить поставщику" }));
    const send = await screen.findByRole("dialog");
    expect(within(send).getByRole("button", { name: "Отправить письмо" })).toBeDisabled();
    fireEvent.change(within(send).getByLabelText("Адрес для письма"), {
      target: { value: "orders@lumber.example" },
    });
    fireEvent.click(within(send).getByRole("button", { name: "Отправить письмо" }));
    expect(await screen.findByText("Заказ отправлен поставщику")).toBeVisible();
  });
});

describe("Склад · приёмка и отгрузки", () => {
  it("«Приёмка»: строка заказа ждёт товара; «Принять» открывает приёмку этой строки", async () => {
    await openStock("supply@demo.example", "receipts");
    const row = within(await rowOf(ORDER));
    expect(row.getByText("Просрочен")).toBeVisible();
    fireEvent.click(
      row.getByRole("button", { name: `Принять «Скрепление рельсовое КБ-65» по заказу ${ORDER}` }),
    );
    const modal = await screen.findByRole("dialog");
    expect(await within(modal).findByText("осталось 30 из 30")).toBeInTheDocument();
  });

  it("отгрузка по проекту: резервы проекта → накладная ОТГ, резерв и остаток уменьшаются", async () => {
    await openStock("supply@demo.example", "shipments");
    fireEvent.change(screen.getByRole("searchbox", { name: "Номер проекта" }), {
      target: { value: "ПР-2026-099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти резервы" }));
    const input = await screen.findByRole("spinbutton", {
      name: "Отгрузить, «Скрепление рельсовое КБ-65»",
    });
    expect(input).toHaveValue("20");
    fireEvent.change(input, { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Трек-номер"), { target: { value: "TRK-100" } });
    fireEvent.click(screen.getByRole("button", { name: "Отгрузить" }));
    expect(await screen.findByText(/Отгружено, накладная ОТГ-\d{4}-001/)).toBeVisible();
    const table = within(await screen.findByRole("table", { name: "Отгрузки по проектам" }));
    expect(table.getByText("TRK-100")).toBeVisible();
    expect(await screen.findByText("в резерве 12 из 20")).toBeVisible();
  });

  it("непроект (заявка ЗВ) не отгружается: понятный отказ", async () => {
    await openStock("supply@demo.example", "shipments");
    fireEvent.change(screen.getByRole("searchbox", { name: "Номер проекта" }), {
      target: { value: "ЗВ-2026-097" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти резервы" }));
    expect(await screen.findByText("Резервов нет")).toBeVisible();
  });
});
