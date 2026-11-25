import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { patchOrderMock } from "../../../mocks/erpStock";
import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { fillDate, pickCompany, searchCompany } from "../../../test/fields";
import { panelEl } from "../../../test/panel";
import { server } from "../../../test/server";
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

describe("Склад · карточка заказа партнёру (ЕД-7)", () => {
  it("каждое сведение — один раз: поставщик в шапке, реквизиты в «Сведениях», журнал только в «Истории»", async () => {
    signIn("supply@demo.example");
    renderAt(ORDER_PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` }),
    ).toBeVisible();
    const side = await panelEl();
    // у карточки нет «Обсуждения», «Маршрута» и «Документов» — вкладок нет
    expect((await within(side).findAllByRole("tab")).map((tab) => tab.textContent)).toEqual([
      "Сведения",
      "История",
    ]);
    // поставщик назван один раз (шапка), почта — только в «Сведениях»
    expect(screen.getAllByText(/Вымышленная Сталь/)).toHaveLength(1);
    expect(within(side).getAllByText(/sales@steel\.example/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Журнал заказа" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Реквизиты заказа" })).toBeNull();
    // журнал — в «Истории», в центре его копии нет
    expect(screen.queryByRole("list", { name: "Журнал заказа" })).toBeNull();
    fireEvent.click(within(side).getByRole("tab", { name: "История" }));
    expect(await within(side).findByRole("list", { name: "Журнал заказа" })).toBeVisible();
    expect(screen.getAllByRole("list", { name: "Журнал заказа" })).toHaveLength(1);
    // и при открытой «Истории» поставщик по-прежнему назван один раз: запись «Заказ создан» его не повторяет
    expect(screen.getAllByText(/Вымышленная Сталь/)).toHaveLength(1);
  });
});

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
    // ЕД-3: партнёр — общая ячейка компании (логотип или буквы названия)
    expect(
      row.getByText("ООО «Вымышленная Сталь»").closest(".pf-entity__text")?.previousElementSibling,
    ).toHaveClass("pf-entity__pic--square");
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
    // события заказа — одно место, вкладка «История» бокового окна (ЕД-7)
    const side = await panelEl();
    fireEvent.click(await within(side).findByRole("tab", { name: "История" }));
    expect((await within(side).findAllByText(/накладная НП-77/)).length).toBeGreaterThan(0);
    // СЦ-10: количество — в единице строки заказа, в журнале и в списке приёмок.
    expect((await screen.findAllByText(/10\sкомпл\. · накладная НП-77/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/^10 компл\. \(C-02-1\)$/)).toBeVisible();
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
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
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
    // Б-2: без даты «Подтвердить» неактивна и говорит почему
    fillDate(within(confirm).getByLabelText("Подтверждённая дата поставки"), "");
    await waitFor(() => {
      expect(submit).toBeDisabled();
    });
    expect(submit).toHaveAccessibleDescription("Укажите подтверждённую дату поставки.");
    fillDate(within(confirm).getByLabelText("Подтверждённая дата поставки"), "2099-01-15");
    fireEvent.click(submit);
    expect(await screen.findByText("Заказ подтверждён")).toBeVisible();
    await screen.findByRole("button", { name: "Принять товар" });
    expect(screen.queryByRole("button", { name: "Отправить партнёру" })).not.toBeInTheDocument();
  });

  it("письмо партнёру не ушло: главная кнопка «Отправить ещё раз», письмо уходит снова, статус не меняется (Б-5)", async () => {
    patchOrderMock(ORDER, {
      status: "sent",
      sentAt: "2026-11-20T09:00:00+05:00",
      sentTo: "sales@steel.example",
      mail: { state: "failed", reason: "smtp_not_configured" },
    });
    signIn("supply@demo.example");
    renderAt(ORDER_PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` }),
    ).toBeVisible();
    // «Партнёр подтвердил» остаётся рядом, но главное — повтор письма
    expect(screen.getByRole("button", { name: "Партнёр подтвердил" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Отправить ещё раз" }));
    const send = await screen.findByRole("dialog");
    fireEvent.click(within(send).getByRole("button", { name: "Отправить письмо" }));
    expect(
      await screen.findByText(/^Заказ оформлен\. Письмо партнёру — в очереди почты/),
    ).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Отправить ещё раз" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Партнёр подтвердил" })).toBeVisible();
  });

  it("письмо ушло: «Отправить ещё раз» не предлагается", async () => {
    patchOrderMock(ORDER, { status: "sent", sentAt: "2026-11-20T09:00:00+05:00" });
    signIn("supply@demo.example");
    renderAt(ORDER_PATH);
    await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ${ORDER}` });
    expect(screen.getByRole("button", { name: "Партнёр подтвердил" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отправить ещё раз" })).not.toBeInTheDocument();
  });

  it("внутреннее примечание и комментарий партнёру: разные поля; комментарий правится в черновике (СЦ-10)", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const page = document.body;
    await pickCompany(
      within(page).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
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
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Лес",
      "ООО «Пример Лес»",
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
    const sendSubmit = within(send).getByRole("button", { name: "Отправить письмо" });
    expect(sendSubmit).toBeDisabled();
    expect(sendSubmit).toHaveAccessibleDescription(
      "Укажите адрес партнёра — без него письмо не уйдёт.",
    );
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

  it("ЕД-4: журнал принятого — строки позицией (миниатюра, название, наш артикул), а не текстом через «;»", async () => {
    const line = (name: string, sku: string, id: string, quantity: number) => ({
      name,
      item: {
        id,
        name,
        sku,
        kind: "goods" as const,
        thumbnail: `/api/v1/erp/catalog/items/${id}/thumbnail?v=1`,
      },
      quantity,
      cell: "A-01-1",
      units: [],
      expiry_date: null,
      doc_number: null,
      doc_valid_until: null,
    });
    server.use(
      http.get("*/api/v1/erp/stock/receipts", () =>
        HttpResponse.json({
          pending: [],
          done: [
            {
              id: "7",
              order_number: ORDER,
              order_path: ORDER_PATH,
              supplier: "Вымышленная Сталь",
              received_at: "2026-11-20T08:00:00Z",
              received_by: { id: "u-demo-supply", name: "Демо Снабженцев", initials: "ДС" },
              supplier_doc: "НКЛ-12",
              quantity: 5,
              lines: [
                line("Рельс Р65", "RT-00031", "31", 3),
                line("Скрепление КБ-65", "RT-00042", "42", 2),
              ],
            },
          ],
          rights: { manage: true, ship: false },
        }),
      ),
    );
    await openStock("supply@demo.example", "receipts");
    const journal = await screen.findByRole("list", { name: "Последние приёмки" });
    const entities = journal.querySelectorAll(".pf-stock-receipt-lines .pf-entity");
    expect(entities).toHaveLength(2);
    expect(within(journal).getByText("RT-00031")).toBeVisible();
    expect(within(journal).getByText("RT-00042")).toBeVisible();
    expect(journal.querySelectorAll('img[src*="/thumbnail?v="]')).toHaveLength(2);
    expect(journal.textContent).not.toContain("; ");
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
    // Б-2: без количества кнопка неактивна, причина названа
    fireEvent.change(input, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Отгрузить" })).toHaveAccessibleDescription(
      "Укажите количество хотя бы по одной позиции.",
    );
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

  it("ЕД-6: партнёр заказа выбирается из контрагентов, а не вписывается; роль формы — «поставщик»; в ERP уходит id выбранной компании", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock/new?mode=shortage&request=ПР-2026-099");
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    let asked: URLSearchParams | undefined;
    const sent: unknown[] = [];
    server.use(
      http.get("*/people/counterparties", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return undefined;
      }),
      http.post("*/erp/stock/orders/from-request", async ({ request }) => {
        sent.push(await request.clone().json());
        return undefined;
      }),
    );
    const partner = await screen.findByRole("combobox", { name: "Партнёр" });
    // вписанный текст партнёром не становится: создать нельзя, поле просит выбор
    searchCompany(partner, "Левый ООО");
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    expect(await screen.findByText("Выберите партнёра")).toBeInTheDocument();
    expect(sent).toEqual([]);
    await waitFor(() => {
      expect(asked?.get("role")).toBe("supplier");
    });
    await pickCompany(partner, "Сталь", "ООО «Вымышленная Сталь»");
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    await waitFor(() => {
      expect(sent).toEqual([{ request: "ПР-2026-099", supplier_id: "5" }]);
    });
  });

  it("ЕД-6: роль поставщика ставится при «Создать черновик», а не при выборе; отказ — без заказа", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock/new?mode=shortage&request=ПР-2026-099");
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const marked: unknown[] = [];
    const sent: unknown[] = [];
    let status = 403;
    server.use(
      http.post("*/people/counterparties/:id/roles", async ({ request }) => {
        marked.push(await request.clone().json());
        return status === 0
          ? undefined
          : HttpResponse.json({ code: "FORBIDDEN", message: "Нет.", source: "erp" }, { status });
      }),
      http.post("*/erp/stock/orders/from-request", async ({ request }) => {
        sent.push(await request.clone().json());
        return undefined;
      }),
    );
    const partner = await screen.findByRole("combobox", { name: "Партнёр" });
    await pickCompany(partner, "Демо-Путь", "АО «Демо-Путь»");
    expect(marked).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    expect(
      await screen.findByText(/Не удалось отметить компанию поставщиком: нет права/),
    ).toBeVisible();
    expect(sent).toEqual([]);
    status = 0;
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    await waitFor(() => {
      expect(sent).toEqual([{ request: "ПР-2026-099", supplier_id: "7" }]);
    });
    expect(marked).toHaveLength(2);
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

  it("Х-18: шаг «Партнёр и способ» получает галочку только по проверке; пока её нет — на шаге названо, чего не хватает", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock/new");
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const first = () => screen.getByRole("button", { name: /^Партнёр и способ/ });
    // пока шаг не покидали, он не пестрит требованиями
    expect(
      within(screen.getByRole("region", { name: /^Партнёр и способ/ })).queryByText(
        "Чтобы шаг был готов:",
      ),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
    expect(tickOf(first())).toBe(false);
    fireEvent.click(first());
    const section = screen.getByRole("region", { name: /^Партнёр и способ/ });
    expect(within(section).getByText("Чтобы шаг был готов:")).toBeVisible();
    expect(within(section).getByText("Выберите партнёра")).toBeVisible();

    const partner = await screen.findByRole("combobox", { name: "Партнёр" });
    await pickCompany(partner, "Демо-Путь", "АО «Демо-Путь»");
    fireEvent.click(screen.getByRole("button", { name: /^Строки/, expanded: false }));
    expect(tickOf(first())).toBe(true);
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

async function createUnpricedDraft(options: { price?: string } = {}) {
  await openStock("supply@demo.example", "orders");
  fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
  await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
  const page = document.body;
  await pickCompany(
    within(page).getByRole("combobox", { name: "Партнёр" }),
    "Сталь",
    "ООО «Вымышленная Сталь»",
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
  if (options.price) {
    fireEvent.change(
      within(page).getByRole("textbox", { name: "Цена партнёра за единицу, строка 1" }),
      {
        target: { value: options.price },
      },
    );
  }
  fireEvent.click(within(page).getByRole("button", { name: "Создать черновик" }));
}

describe("Склад · заказ без цены и даты не уходит партнёру (СЦ-10)", () => {
  it("карточка говорит, чего не хватает; цена и дата в «Изменить» открывают отправку", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    const page = document.body;
    await pickCompany(
      within(page).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
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

  it("«Отмена» на странице нового заказа ведёт к заказам, а не на склад (Б-4)", async () => {
    await openStock("supply@demo.example", "orders");
    fireEvent.click(await screen.findByRole("link", { name: "Создать заказ" }));
    await screen.findByRole("heading", { level: 1, name: "Новый заказ партнёру" });
    expect(screen.getByRole("link", { name: "Отмена" })).toHaveAttribute(
      "href",
      "/erp/stock?view=orders",
    );
    expect(screen.getByText(/Без даты и цен заказ партнёру не уйдёт/)).toBeInTheDocument();
  });

  it("черновик с ценой, но без даты: главная кнопка «Указать дату» открывает «Изменить» (Б-4)", async () => {
    await createUnpricedDraft({ price: "185000" });
    const year = String(new Date().getFullYear());
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ЗП-${year}-030` }),
    ).toBeVisible();
    expect(screen.getByText("Нет ожидаемой даты")).toBeVisible();
    expect(screen.getByText(/Укажите дату — без неё заказ партнёру не уходит/)).toBeVisible();
    expect(screen.queryByText(/Внесите в «Изменить»/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Отправить партнёру" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Указать дату" }));
    const edit = await screen.findByRole("dialog");
    fillDate(within(edit).getByLabelText("Ожидаемая дата"), FUTURE);
    fireEvent.click(within(edit).getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("button", { name: "Отправить партнёру" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Указать дату" })).toBeNull();
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

/** СЦ-7 (F): количества от тысячи и дробные идут через общий формат — с разрядами и запятой. */
describe("Склад · количества с разрядами (СЦ-7)", () => {
  it("отгрузка: «в резерве 1 200 из 2 500» — с разрядами", async () => {
    server.use(
      http.get("*/api/v1/erp/stock/reservations", () =>
        HttpResponse.json({
          items: [
            {
              id: "9001",
              product_id: "1",
              product_name: "Рельс Р65",
              request: { number: "ПР-2026-099", client: null, path: "/eds/projects/x" },
              line_id: null,
              quantity: 2500,
              shipped_quantity: 1300,
              remaining: 1200,
              status: "active",
              created_at: "2026-11-01T10:00:00+05:00",
              created_by: null,
              tracking: "none",
              units: [],
            },
          ],
        }),
      ),
    );
    await openStock("supply@demo.example", "shipments");
    fireEvent.change(screen.getByRole("searchbox", { name: "Номер проекта" }), {
      target: { value: "ПР-2026-099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти резервы" }));
    expect(await screen.findByText(/^в резерве 1\s200 из 2\s500$/)).toBeVisible();
  });

  it("прослеживаемость: «отгружено 0,5 из 1 500» — с разрядами и запятой", async () => {
    server.use(
      http.get("*/api/v1/erp/stock/trace", () =>
        HttpResponse.json({
          items: [
            {
              id: "7001",
              kind: "lot",
              number: "LOT-BIG",
              expiry_date: null,
              quantity: 1500,
              shipped_quantity: 0.5,
              status: "in_stock",
              product: { id: "1", name: "Смазка", article: "СМ-1" },
              origin: {
                received_at: "2026-11-01T10:00:00+05:00",
                supplier_doc: null,
                order_number: ORDER,
                order_path: ORDER_PATH,
                supplier: "Партнёр",
                manufacturer: null,
                doc_number: null,
                doc_valid_until: null,
                request: null,
              },
              destinations: [],
            },
          ],
        }),
      ),
    );
    signIn("supply@demo.example");
    renderAt("/erp/stock?view=trace&q=LOT-BIG");
    expect(await screen.findByText(/отгружено 0,5 из 1\s500/)).toBeVisible();
  });
});

describe("Склад · ссылка партнёра в Кабинете (ДК-5)", () => {
  async function openOrder(email: string, order: string) {
    signIn(email);
    renderAt(`/erp/stock/${encodeURIComponent(order)}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Заказ партнёру ${order}` }),
    ).toBeVisible();
  }

  it("снабженец видит, кому из партнёра ушла ссылка на отправленный заказ, и отзывает её одним подтверждением", async () => {
    await openOrder("supply@demo.example", ORDER);
    const heading = await screen.findByRole("heading", { name: "Ссылка партнёра в Кабинете" });
    const card = heading.closest<HTMLElement>(".ant-card");
    if (!card) throw new Error("нет блока ссылки партнёра");
    expect(within(card).getByText("Получатель — d***@steel.example.")).toBeVisible();
    expect(within(card).getByText("Партнёр ещё не открывал.")).toBeVisible();
    expect(screen.queryByText(/Клиент ещё не открывал/)).toBeNull();

    fireEvent.click(within(card).getByRole("button", { name: "Отозвать ссылку" }));
    expect(
      await screen.findByRole("dialog", { name: "Отозвать ссылку на заказ?" }),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));
    expect(
      await within(card).findByText(/Ссылка отозвана: партнёр по ней ничего не откроет/),
    ).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Отозвать ссылку" })).toBeNull();
  });
});
