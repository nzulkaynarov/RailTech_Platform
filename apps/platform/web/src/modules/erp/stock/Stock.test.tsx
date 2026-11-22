import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { fillDate } from "../../../test/fields";
import { listSettled } from "../../../test/settled";

setupCalcTests();

const FUTURE = `${String(new Date().getFullYear() + 1)}-01-15`;
const ORDER = `ЗП-${String(new Date().getFullYear())}-029`;
const ORDER_PATH = `/erp/stock/${encodeURIComponent(ORDER)}`;

/** Галочка (`StepSections`): в кружке svg, и шаг не помечен «нужно исправить» (там тоже svg). */
function tickOf(head: HTMLElement): boolean {
  return (
    head.querySelector(".pf-fstep-badge svg") !== null &&
    head.closest("li")?.getAttribute("data-invalid") === null
  );
}

async function openStock(email: string, view = "") {
  signIn(email);
  renderAt(`/erp/stock${view ? `?view=${view}` : ""}`);
  const heading = view === "orders" ? "Закупки" : "Склад";
  expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeVisible();
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

describe("Склад · заказы партнёрам", () => {
  it("список: ЗП-номер, партнёр, ожидаемая дата и просрочка, статус, приёмка, сумма", async () => {
    await openStock("supply@demo.example", "orders");
    const table = within(await screen.findByRole("table", { name: "Заказы партнёрам" }));
    const row = within(await rowOf(ORDER));
    expect(row.getByText("ООО «Вымышленная Сталь»")).toBeVisible();
    expect(row.getByText("Подтверждён")).toBeVisible();
    expect(row.getByText("Просрочен · 3 дн.")).toBeVisible();
    expect(row.getByText("0 из 30")).toBeVisible();
    expect(table.getByRole("columnheader", { name: "Сумма" })).toBeVisible();
    expect(row.getByText(/5\s?550\s?000/)).toBeVisible();
  });

  it("цены партнёров скрыты от роли без них: нет колонки «Сумма»", async () => {
    await openStock("engineer@demo.example", "orders");
    const table = within(await screen.findByRole("table", { name: "Заказы партнёрам" }));
    expect(table.queryByRole("columnheader", { name: "Сумма" })).not.toBeInTheDocument();
    expect(screen.queryByText(/5\s?550\s?000/)).not.toBeInTheDocument();
  });

  it("карточка просроченного заказа: предупреждение, состав, «Принять товар» частично и полностью", async () => {
    signIn("supply@demo.example");
    renderAt(ORDER_PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` }),
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
    fireEvent.change(within(modal).getByRole("textbox", { name: "Накладная партнёра" }), {
      target: { value: "НП-77" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    expect(await screen.findByText("Товар принят")).toBeVisible();
    expect((await screen.findAllByText(/накладная НП-77/)).length).toBeGreaterThan(0);
    // СЦ-10: количество — в единице строки заказа, в журнале и в списке приёмок.
    expect((await screen.findAllByText(/10\sкомпл\. · накладная НП-77/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/· 10 компл\. \(C-02-1\)/)).toBeVisible();
    expect(screen.getAllByText("Подтверждён").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Принять товар" }));
    modal = await screen.findByRole("dialog");
    expect(await within(modal).findByText("осталось 20 из 30 компл.")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Принять товар" })).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("Получен").length).toBeGreaterThan(0);
  });

  it("новый заказ: черновик → отправлен (письмо в журнале) → подтверждён; недопустимые кнопки не показываются", async () => {
    await openStock("supply@demo.example", "orders");
    // новый заказ — страница с секциями (platform-frontend.md §4.1a)
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const modal = document.body;
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Партнёр" }));
    fireEvent.click(
      await screen.findByText("ООО «Вымышленная Сталь»", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
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
    // СЦ-10: без цены и ожидаемой даты заказ партнёру не уходит.
    fireEvent.change(
      within(modal).getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" }),
      {
        target: { value: "250" },
      },
    );
    fillDate(within(modal).getByLabelText("Ожидаемая дата"), FUTURE);
    fireEvent.click(within(modal).getByRole("button", { name: "Создать черновик" }));

    const year = String(new Date().getFullYear());
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ЗП-${year}-030` }),
    ).toBeVisible();
    expect(screen.getAllByText("Черновик").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Принять товар" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Партнёр подтвердил" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Отправить партнёру" }));
    const send = await screen.findByRole("dialog");
    fireEvent.click(within(send).getByRole("button", { name: "Отправить письмо" }));
    // 0.10 (FR-12): «отправлено» не пишем заранее — письмо в очереди почтового сервиса, итог в карточке
    expect(
      await screen.findByText(/^Заказ оформлен\. Письмо партнёру — в очереди почты/),
    ).toBeVisible();
    await screen.findByRole("button", { name: "Партнёр подтвердил" });
    expect(screen.getAllByText(/sales@steel\.example/).length).toBeGreaterThan(0);
    expect(screen.getByText("в очереди почты — итог появится здесь")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Партнёр подтвердил" }));
    const confirm = await screen.findByRole("dialog");
    const submit = within(confirm).getByRole("button", { name: "Подтвердить" });
    // Ожидаемая дата заказа (без неё он не ушёл бы, СЦ-10) подставлена — партнёр подтвердил её или новую.
    expect(submit).toBeEnabled();
    fillDate(within(confirm).getByLabelText("Подтверждённая дата поставки"), "2099-01-15");
    fireEvent.click(submit);
    expect(await screen.findByText("Заказ подтверждён")).toBeVisible();
    await screen.findByRole("button", { name: "Принять товар" });
    expect(screen.queryByRole("button", { name: "Отправить партнёру" })).not.toBeInTheDocument();
  });

  it("внутреннее примечание и комментарий партнёру: разные поля; комментарий правится в черновике (СЦ-10)", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const page = document.body;
    fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Партнёр" }));
    fireEvent.click(
      await screen.findByText("ООО «Вымышленная Сталь»", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
    expect(screen.getByText("Партнёр его не увидит.")).toBeVisible();
    fireEvent.change(within(page).getByLabelText("Внутреннее примечание"), {
      target: { value: "Под проект клиента" },
    });
    fireEvent.change(within(page).getByLabelText("Комментарий партнёру"), {
      target: { value: "Отгрузка до станции Сергели" },
    });
    fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Товар, строка 1" }));
    fireEvent.change(within(page).getByRole("combobox", { name: "Товар, строка 1" }), {
      target: { value: "перевод" },
    });
    fireEvent.click(
      await screen.findByText(/Перевод стрелочный Р65 марки 1\/11/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.change(within(page).getByRole("spinbutton", { name: "Количество, строка 1" }), {
      target: { value: "1" },
    });
    // СЦ-10: без цены и ожидаемой даты заказ партнёру не уходит.
    fireEvent.change(
      within(page).getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" }),
      {
        target: { value: "250" },
      },
    );
    fillDate(within(page).getByLabelText("Ожидаемая дата"), FUTURE);
    fireEvent.click(within(page).getByRole("button", { name: "Создать черновик" }));

    await screen.findByRole("button", { name: "Отправить партнёру" });
    expect(screen.getByText("Отгрузка до станции Сергели")).toBeVisible();
    expect(screen.getByText("Под проект клиента")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    const edit = await screen.findByRole("dialog");
    fireEvent.change(within(edit).getByLabelText("Комментарий партнёру"), {
      target: { value: "Отгрузка двумя партиями" },
    });
    fireEvent.click(within(edit).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Заказ сохранён")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(
      screen.getByText("Отгрузка двумя партиями", { selector: ":not(textarea)" }),
    ).toBeVisible();
    expect(screen.queryByText("Отгрузка до станции Сергели")).not.toBeInTheDocument();
  });

  it("партнёр без почты: отправка требует адрес", async () => {
    await openStock("supply@demo.example", "orders");
    // новый заказ — страница с секциями (platform-frontend.md §4.1a)
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const modal = document.body;
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Партнёр" }));
    fireEvent.click(
      await screen.findByText(/ООО «Пример Лес» · нет почты/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
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
    // СЦ-10: без цены и ожидаемой даты заказ партнёру не уходит.
    fireEvent.change(
      within(modal).getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" }),
      {
        target: { value: "250" },
      },
    );
    fillDate(within(modal).getByLabelText("Ожидаемая дата"), FUTURE);
    fireEvent.click(within(modal).getByRole("button", { name: "Создать черновик" }));
    await screen.findByRole("button", { name: "Отправить партнёру" });
    fireEvent.click(screen.getByRole("button", { name: "Отправить партнёру" }));
    const send = await screen.findByRole("dialog");
    expect(within(send).getByRole("button", { name: "Отправить письмо" })).toBeDisabled();
    fireEvent.change(within(send).getByLabelText("Адрес для письма"), {
      target: { value: "orders@lumber.example" },
    });
    fireEvent.click(within(send).getByRole("button", { name: "Отправить письмо" }));
    expect(
      await screen.findByText(/^Заказ оформлен\. Письмо партнёру — в очереди почты/),
    ).toBeVisible();
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
    expect(await within(modal).findByText("осталось 30 из 30 компл.")).toBeInTheDocument();
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

  it("СЦ-9: отгрузка открыта из «Моих задач» с ?request= — проект уже найден, резервы показаны", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock?view=shipments&request=ПР-2026-099");
    expect(await screen.findByRole("searchbox", { name: "Номер проекта" })).toHaveValue(
      "ПР-2026-099",
    );
    expect(
      await screen.findByRole("spinbutton", { name: "Отгрузить, «Скрепление рельсовое КБ-65»" }),
    ).toHaveValue("20");
  });

  it("СЦ-9: новый заказ открыт с ?mode=shortage&request= — режим и номер проекта подставлены", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock/new?mode=shortage&request=ПР-2026-099");
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    expect(await screen.findByRole("radio", { name: "На дефицит заявки" })).toBeChecked();
    expect(screen.getByRole("textbox", { name: /Номер заявки|Заявка|Проект/ })).toHaveValue(
      "ПР-2026-099",
    );
  });

  it("Х-18: шаг «Строки» без количества не получает галочку; с количеством — получает", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock/new");
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const page = document.body;
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
    fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Товар, строка 1" }));
    fireEvent.change(within(page).getByRole("combobox", { name: "Товар, строка 1" }), {
      target: { value: "перевод" },
    });
    fireEvent.click(
      await screen.findByText(/Перевод стрелочный Р65 марки 1\/11/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    const lines = () => screen.getByRole("button", { name: /^Строки/ });
    fireEvent.click(screen.getByRole("button", { name: /^Партнёр и способ/, expanded: false }));
    expect(tickOf(lines())).toBe(false); // позиция выбрана, количества нет — форма это не пропустит
    fireEvent.click(lines());
    fireEvent.change(within(page).getByRole("spinbutton", { name: "Количество, строка 1" }), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Партнёр и способ/, expanded: false }));
    expect(tickOf(lines())).toBe(true);
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

async function createUnpricedDraft() {
  await openStock("supply@demo.example", "orders");
  fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
  await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
  const page = document.body;
  fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Партнёр" }));
  fireEvent.click(
    await screen.findByText("ООО «Вымышленная Сталь»", {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
  fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Товар, строка 1" }));
  fireEvent.change(within(page).getByRole("combobox", { name: "Товар, строка 1" }), {
    target: { value: "перевод" },
  });
  fireEvent.click(
    await screen.findByText(/Перевод стрелочный Р65 марки 1\/11/, {
      selector: ".ant-select-item-option-content",
    }),
  );
  fireEvent.change(within(page).getByRole("spinbutton", { name: "Количество, строка 1" }), {
    target: { value: "1" },
  });
  fireEvent.click(within(page).getByRole("button", { name: "Создать черновик" }));
}

describe("Склад · заказ без цены и даты не уходит партнёру (СЦ-10)", () => {
  it("карточка говорит, чего не хватает; цена и дата в «Изменить» открывают отправку", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const page = document.body;
    fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Партнёр" }));
    fireEvent.click(
      await screen.findByText("ООО «Вымышленная Сталь»", {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
    fireEvent.mouseDown(within(page).getByRole("combobox", { name: "Товар, строка 1" }));
    fireEvent.change(within(page).getByRole("combobox", { name: "Товар, строка 1" }), {
      target: { value: "перевод" },
    });
    fireEvent.click(
      await screen.findByText(/Перевод стрелочный Р65 марки 1\/11/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    fireEvent.change(within(page).getByRole("spinbutton", { name: "Количество, строка 1" }), {
      target: { value: "1" },
    });
    fireEvent.click(within(page).getByRole("button", { name: "Создать черновик" }));

    const year = String(new Date().getFullYear());
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ЗП-${year}-030` }),
    ).toBeVisible();
    expect(screen.getByText("Без цены: 1 строка · Нет ожидаемой даты")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отправить партнёру" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    const edit = await screen.findByRole("dialog");
    const price = within(edit).getByRole("textbox", { name: /^Цена, «Перевод стрелочный/ });
    fireEvent.change(price, { target: { value: "185000" } });
    fillDate(within(edit).getByLabelText("Ожидаемая дата"), FUTURE);
    fireEvent.click(within(edit).getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByRole("button", { name: "Отправить партнёру" })).toBeVisible();
    expect(screen.queryByText(/Без цены/)).toBeNull();
  });

  it("«Запросить цену»: строки без цены уходят партнёру, карточка показывает, что запрос отправлен", async () => {
    await createUnpricedDraft();
    const year = String(new Date().getFullYear());
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ЗП-${year}-030` }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Запросить цену" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByText("Партнёр получит запрос по 1 строке без цены."),
    ).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Комментарий партнёру"), {
      target: { value: "Нужна цена до пятницы" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить запрос" }));

    expect(await screen.findByText(/Запрос цены отправлен .* — ждём ответа\./)).toBeVisible();
    expect(screen.getByText("Без цены: 1 строка · Нет ожидаемой даты")).toBeVisible();
  });
});
