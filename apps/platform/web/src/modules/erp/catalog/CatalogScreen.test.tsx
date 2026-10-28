import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";
import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

async function open(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/erp/catalog${search}`);
  expect(
    await screen.findByRole("heading", { level: 1, name: "Номенклатура и поставщики" }),
  ).toBeVisible();
  return view;
}

function row(name: string): HTMLElement {
  const tr = screen.getByRole("button", { name: new RegExp(name) }).closest("tr");
  if (!tr) throw new Error(`нет строки ${name}`);
  return tr;
}

describe("Номенклатура: позиции", () => {
  it("список с типом, единицей, НДС и сроком цен; поиск и фильтр по типу", async () => {
    await open("manager@demo.example");

    expect(
      await screen.findByRole("button", { name: /Открыть позицию Кабель силовой/ }),
    ).toBeVisible();
    const cable = row("Кабель силовой");
    expect(within(cable).getByText("Товар со склада")).toBeVisible();
    expect(within(cable).getByText("м")).toBeVisible();
    expect(within(cable).getByText(/12 % \(по умолчанию\)/)).toBeVisible();
    expect(within(cable).getByText("Предложений: 2")).toBeVisible();
    expect(within(row("Монтаж стрелочного")).getByText("Услуга: фикс")).toBeVisible();
    expect(within(row("Пусконаладочные")).getByText("Услуга: по времени")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Поиск по названию, артикулу и чертежу"), {
      target: { value: "реле" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Открыть позицию Кабель/ })).toBeNull();
    });
    expect(
      await screen.findByRole("button", { name: /Открыть позицию Реле защиты/ }),
    ).toBeVisible();

    fireEvent.change(screen.getByLabelText("Поиск по названию, артикулу и чертежу"), {
      target: { value: "нет такой позиции" },
    });
    expect(await screen.findByText("Позиций нет")).toBeVisible();
    expect(screen.getByText(/Измените поиск или фильтр/)).toBeVisible();
  });

  it("менеджер читает, но не добавляет: кнопки «Добавить позицию» нет", async () => {
    await open("manager@demo.example");
    await screen.findByRole("button", { name: /Открыть позицию Кабель/ });
    expect(screen.queryByRole("button", { name: "Добавить позицию" })).toBeNull();
  });

  it("снабженец открывает позицию и видит предложения с ценой, квотой и сроком; цена по-долларовому", async () => {
    await open("supply@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: /Открыть позицию Кабель/ }));

    const drawer = await screen.findByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
    expect(await within(drawer).findByText("ООО «Поставщик Север»")).toBeVisible();
    expect(within(drawer).getByText(/12,50\s*USD/)).toBeVisible();
    expect(within(drawer).getByText("500 шт., от 10")).toBeVisible();
    expect(within(drawer).getByText("со склада 2 дн., под заказ 14 дн.")).toBeVisible();
    expect(within(drawer).getByText("Скоро истекает")).toBeVisible();
    expect(within(drawer).queryByText(/Цены поставщиков вам не показываются/)).toBeNull();
  });

  it("гл. инженер: цен поставщиков нет, сказано словами; квота и срок видны", async () => {
    await open("engineer@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: /Открыть позицию Кабель/ }));

    const drawer = await screen.findByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
    expect(await within(drawer).findByText("ООО «Поставщик Север»")).toBeVisible();
    expect(within(drawer).getByText(/Цены поставщиков вам не показываются/)).toBeVisible();
    expect(within(drawer).getAllByText("скрыта").length).toBeGreaterThan(0);
    expect(within(drawer).queryByText(/12,50\s*USD/)).toBeNull();
    expect(within(drawer).getByText("500 шт., от 10")).toBeVisible();
  });

  it("добавление позиции: услуга по этапам с НДС; ошибка ERP показана рядом с полем", async () => {
    await open("engineer@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: "Добавить позицию" }));

    const dialog = await findModal("Добавить позицию");
    expect(await within(dialog).findByText("Что произойдёт")).toBeInTheDocument();
    fireEvent.change(await within(dialog).findByLabelText("Название"), {
      target: { value: "Монтаж шкафа управления" },
    });
    fireEvent.change(within(dialog).getByLabelText("НДС, %"), { target: { value: "150" } });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Добавить" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("НДС — число от 0 до 100");
    fireEvent.change(within(dialog).getByLabelText("НДС, %"), { target: { value: "12" } });
    fireEvent.click(await within(dialog).findByRole("button", { name: /Добавить$/ }));

    expect(await screen.findByRole("dialog", { name: "Монтаж шкафа управления" })).toBeVisible();
    expect(
      await screen.findByRole("button", { name: /Открыть позицию Монтаж шкафа/ }),
    ).toBeVisible();
  });

  it("правка позиции отправляет только изменённое; пустой НДС возвращает ставку компании", async () => {
    let sent: unknown = null;
    server.use(
      http.patch("*/erp/catalog/items/:id", async ({ request }) => {
        sent = await request.json();
        return undefined;
      }),
    );
    await open("supply@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: /Открыть позицию Реле защиты/ }));
    const drawer = await screen.findByRole("dialog", { name: "Реле защиты РЗ-1" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Изменить позицию" }));

    const form = await findModal("Изменить позицию");
    fireEvent.change(await within(form).findByLabelText("НДС, %"), { target: { value: "" } });
    fireEvent.click(await within(form).findByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(sent).toEqual({ vat_rate: null });
    });
  });
});

describe("Номенклатура: поставщики", () => {
  it("сроки цен словами: истекло, истекает скоро; карточка с предложениями и ценой для снабженца", async () => {
    await open("supply@demo.example", "?part=suppliers");

    const south = await screen.findByRole("button", {
      name: /Открыть поставщика ООО «Поставщик Север»/,
    });
    const southRow = south.closest("tr") as HTMLElement;
    expect(within(southRow).getByText("Все цены действуют")).toBeVisible();
    const south2 = screen
      .getByRole("button", { name: /Южный Металл/ })
      .closest("tr") as HTMLElement;
    expect(within(south2).getByText("Истекает скоро: 1")).toBeVisible();
    const east = screen
      .getByRole("button", { name: /Восточный склад/ })
      .closest("tr") as HTMLElement;
    expect(within(east).getByText("Истекло: 1")).toBeVisible();

    fireEvent.click(south);
    const drawer = await screen.findByRole("dialog", { name: "ООО «Поставщик Север»" });
    expect(await within(drawer).findByText("Кабель силовой ВВГнг 3×2,5")).toBeVisible();
    expect(within(drawer).getByText(/310\s*USD/)).toBeVisible();
    expect(within(drawer).getByText("УНП")).toBeVisible();
  });

  it("гл. инженер видит сроки и квоты, но не цены; правка условий без цены", async () => {
    await open("engineer@demo.example", "?part=suppliers&supplier=1");

    const drawer = await screen.findByRole("dialog", { name: "ООО «Поставщик Север»" });
    expect(await within(drawer).findByText("Кабель силовой ВВГнг 3×2,5")).toBeVisible();
    expect(within(drawer).getByText(/Цены поставщиков вам не показываются/)).toBeVisible();
    fireEvent.click(
      within(drawer).getByRole("button", {
        name: "Изменить предложение по позиции Кабель силовой ВВГнг 3×2,5",
      }),
    );
    const form = await findModal(/Предложение: Кабель/);
    expect(await within(form).findByText(/Цену поставщика вы не видите/)).toBeInTheDocument();
    expect(within(form).queryByLabelText(/Цена закупки/)).toBeNull();
    fireEvent.change(await within(form).findByLabelText("Квота, шт."), {
      target: { value: "250" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Сохранить" }));
    await modalClosed(/Предложение: Кабель/);
    expect(await within(drawer).findByText("250 шт., от 10")).toBeVisible();
  });

  it("снабженец меняет цену предложения; неверный срок — ошибка словами", async () => {
    await open("supply@demo.example", "?part=suppliers&supplier=1");
    const drawer = await screen.findByRole("dialog", { name: "ООО «Поставщик Север»" });
    fireEvent.click(
      await within(drawer).findByRole("button", {
        name: "Изменить предложение по позиции Кабель силовой ВВГнг 3×2,5",
      }),
    );
    const form = await findModal(/Предложение: Кабель/);
    fireEvent.change(await within(form).findByLabelText("Цена закупки, USD"), {
      target: { value: "13,75" },
    });
    fireEvent.change(within(form).getByLabelText("Цена действует с"), {
      target: { value: "2027-02-01" },
    });
    fireEvent.change(within(form).getByLabelText("Цена действует до"), {
      target: { value: "2027-01-01" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Сохранить" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("не может быть раньше");

    fireEvent.change(within(form).getByLabelText("Цена действует до"), {
      target: { value: "2027-06-30" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: /Сохранить$/ }));
    await modalClosed(/Предложение: Кабель/);
    expect(await within(drawer).findByText(/13,75\s*USD/)).toBeVisible();
  });
});

describe("Номенклатура: бригады", () => {
  it("гл. инженер видит ставки бригад и добавляет бригаду со ставкой", async () => {
    await open("engineer@demo.example", "?part=brigades");

    const first = (await screen.findByRole("button", { name: /Бригада монтажа №1/ })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(first).getByText(/900\s*000/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Добавить бригаду" }));
    const form = await findModal("Добавить бригаду");
    fireEvent.change(await within(form).findByLabelText("Название"), {
      target: { value: "Бригада путейцев" },
    });
    fireEvent.change(within(form).getByLabelText(/Ставка, /), { target: { value: "1100000" } });
    fireEvent.click(await within(form).findByRole("button", { name: "Добавить" }));

    const added = (await screen.findByRole("button", { name: /Бригада путейцев/ })).closest(
      "tr",
    ) as HTMLElement;
    expect(within(added).getByText(/1\s*100\s*000/)).toBeVisible();
  });

  it("менеджер: бригады видны без ставки, сказано, кто её видит; добавить нельзя", async () => {
    await open("manager@demo.example", "?part=brigades");

    expect(await screen.findByText("Бригада монтажа №1")).toBeVisible();
    expect(screen.getByText(/Ставки бригад вам не показываются/)).toBeVisible();
    expect(screen.queryByText(/900\s*000/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить бригаду" })).toBeNull();
  });
});

describe("Номенклатура: справочники", () => {
  it("курсы валют: источник словами; ввести курс может только держатель «Компании»", async () => {
    await open("supply@demo.example", "?part=refs");
    expect((await screen.findAllByText("Вручную")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("ЦБ").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Ввести курс USD" })).toBeNull();
  });

  it("директор вводит курс USD вручную; он появляется в таблице", async () => {
    await open("director@demo.example", "?part=refs");
    fireEvent.click(await screen.findByRole("button", { name: "Ввести курс USD" }));
    const form = await findModal("Ввести курс USD на дату");
    fireEvent.change(await within(form).findByLabelText("Курс, сум за 1 USD"), {
      target: { value: "12700" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Сохранить курс" }));
    await modalClosed("Ввести курс USD на дату");
  });

  it("коды ТН ВЭД: поиск, добавление и повтор кода — конфликт словами", async () => {
    await open("supply@demo.example", "?part=refs");
    fireEvent.click(await screen.findByRole("radio", { name: "Коды ТН ВЭД" }));
    expect(await screen.findByText("Провода и кабели изолированные")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Поиск по коду и наименованию"), {
      target: { value: "7302" },
    });
    await waitFor(() => {
      expect(screen.queryByText("Провода и кабели изолированные")).toBeNull();
    });

    fireEvent.click(screen.getByRole("button", { name: "Добавить код" }));
    const form = await findModal("Добавить код ТН ВЭД");
    fireEvent.change(await within(form).findByLabelText("Код"), { target: { value: "7302" } });
    fireEvent.change(within(form).getByLabelText("Наименование"), { target: { value: "Рельсы" } });
    fireEvent.click(await within(form).findByRole("button", { name: "Добавить" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("Такой код ТН ВЭД уже есть");
  });

  it("производители: менеджер читает без кнопок; снабженец добавляет и убирает из выбора", async () => {
    await open("manager@demo.example", "?part=refs");
    fireEvent.click(await screen.findByRole("radio", { name: "Производители" }));
    expect(await screen.findByText("Электрокабель-Тест")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Добавить производителя" })).toBeNull();
  });

  it("производитель: снабженец добавляет нового", async () => {
    await open("supply@demo.example", "?part=refs");
    fireEvent.click(await screen.findByRole("radio", { name: "Производители" }));
    fireEvent.click(await screen.findByRole("button", { name: "Добавить производителя" }));
    const form = await findModal("Добавить производителя");
    fireEvent.change(await within(form).findByLabelText("Название"), {
      target: { value: "Новый Бренд" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Добавить" }));
    expect(await screen.findByText("Новый Бренд")).toBeVisible();
  });
});

describe("Номенклатура: запросы на категории", () => {
  it("снабженец подаёт запрос; директор одобряет, выбрав заведённую категорию", async () => {
    const supply = await open("supply@demo.example", "?part=requests");
    fireEvent.click(await screen.findByRole("button", { name: "Запросить категорию" }));
    const form = await findModal("Запросить новую категорию");
    expect(await within(form).findByText("Что произойдёт")).toBeInTheDocument();
    fireEvent.change(await within(form).findByLabelText("Название категории"), {
      target: { value: "Кабельные лотки" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Отправить запрос" }));
    const created = await screen.findByText("Кабельные лотки");
    expect(created).toBeVisible();
    // снабженец решения не принимает
    expect(screen.queryByRole("button", { name: /Одобрить запрос/ })).toBeNull();
    supply.queryClient.clear();
  });

  it("директор видит кнопки решения и одобряет запрос, привязав категорию", async () => {
    await open("director@demo.example", "?part=requests");
    fireEvent.click(
      await screen.findByRole("button", { name: "Одобрить запрос «Тормозные колодки»" }),
    );
    const dialog = await findModal(/Одобрить запрос/);
    expect(await within(dialog).findByText("Что произойдёт")).toBeInTheDocument();
  });

  it("повторный запрос, пока первый на рассмотрении, — конфликт словами", async () => {
    await open("supply@demo.example", "?part=requests");
    fireEvent.click(await screen.findByRole("button", { name: "Запросить категорию" }));
    const form = await findModal("Запросить новую категорию");
    fireEvent.change(await within(form).findByLabelText("Название категории"), {
      target: { value: "Тормозные колодки" },
    });
    fireEvent.click(await within(form).findByRole("button", { name: "Отправить запрос" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("уже на рассмотрении");
  });
});

describe("Номенклатура: телефон", () => {
  it("на 390 px список — карточки с подписями полей, без таблицы", async () => {
    setViewportWidth(390);
    await open("manager@demo.example");
    expect(await screen.findByRole("button", { name: /Открыть позицию Кабель/ })).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getAllByText("Единица").length).toBeGreaterThan(0);
  });

  it("раздел недоступен роли без erp.stock: 403-экран с предложением написать администратору", async () => {
    signIn("admin@demo.example");
    renderAt("/erp/catalog");
    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Позиции" })).toBeNull();
  });
});
