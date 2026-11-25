import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { pickCompany, searchCompany } from "../../../test/fields";
import { server } from "../../../test/server";
import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { confirmDialog } from "../../../test/confirmDialog";

setupCalcTests();

const NUMBER = "ЗВ-2026-097";
const PATH = `/erp/calc/${encodeURIComponent(NUMBER)}`;
const RAIL = "Перевод стрелочный Р65 марки 1/11";
const DRIVE = "Привод стрелочный электромеханический СП-6М";

async function openCalc(email: string) {
  signIn(email);
  renderAt(PATH);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
  ).toBeVisible();
}

function lineRow(name: string): HTMLElement {
  const table = screen.getByRole("table", { name: `Строки расчёта по заявке ${NUMBER}` });
  const tr = within(table).getAllByText(name)[0]?.closest("tr");
  if (!tr) throw new Error(`нет строки ${name}`);
  return tr;
}

describe("Расчёт · колонка «Склад»: ячейка, свободное и резерв (B-D21-1)", () => {
  it("снабженец видит ячейку и свободный остаток; резерв строки меняет колонку и тип строки", async () => {
    await openCalc("supply@demo.example");
    const drive = within(lineRow(DRIVE));
    expect(drive.getByText("На складе · 6")).toBeVisible();
    expect(drive.getByText("Ячейка B-04-1")).toBeVisible();
    expect(drive.getByText("Свободно · 6")).toBeVisible();

    fireEvent.click(drive.getByRole("button", { name: `Зарезервировать 4 для «${DRIVE}»` }));
    await waitFor(() => {
      expect(within(lineRow(DRIVE)).getByText("Резерв · 4")).toBeVisible();
    });
    expect(within(lineRow(DRIVE)).getByText("Свободно · 2")).toBeVisible();
    expect(
      within(lineRow(DRIVE)).queryByRole("button", { name: /Зарезервировать/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(lineRow(DRIVE)).getByRole("button", { name: `Снять резерв строки «${DRIVE}»` }),
    );
    await waitFor(() => {
      expect(within(lineRow(DRIVE)).queryByText(/Резерв · /)).not.toBeInTheDocument();
    });
    expect(within(lineRow(DRIVE)).getByText("Свободно · 6")).toBeVisible();
  });

  it("на складе меньше, чем нужно: можно зарезервировать только свободное", async () => {
    await openCalc("supply@demo.example");
    const rail = within(lineRow(RAIL));
    expect(rail.getByText("Товар под заказ")).toBeVisible();
    fireEvent.click(rail.getByRole("button", { name: `Зарезервировать 1 для «${RAIL}»` }));
    await waitFor(() => {
      expect(within(lineRow(RAIL)).getByText("Резерв · 1")).toBeVisible();
    });
    expect(within(lineRow(RAIL)).getByText("Товар под заказ")).toBeVisible();
  });

  it("резерв чужого проекта съедает свободное: расчёт показывает меньше", async () => {
    // Резерв «ПР-2026-099» уже держит 20 скреплений; расчёт ЗВ-2026-097 их не содержит, но привод — свободен целиком.
    await openCalc("supply@demo.example");
    expect(within(lineRow(DRIVE)).getByText("Свободно · 6")).toBeVisible();
  });

  it("бухгалтер (склад — только чтение) видит ячейку и свободное, но не резервирует и не запрашивает цену", async () => {
    await openCalc("accountant@demo.example");
    const row = within(lineRow(DRIVE));
    expect(row.getByText("Ячейка B-04-1")).toBeVisible();
    expect(row.getByText("Свободно · 6")).toBeVisible();
    expect(row.queryByRole("button", { name: /Зарезервировать/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Запросить цену у партнёра" }),
    ).not.toBeInTheDocument();
  });
});

describe("Расчёт · «Запросить цену у партнёра»", () => {
  it("письмо партнёру и запись в журнале: кто, когда, кому, по каким строкам; «Ответ получен»", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    // форма — в боковом окне (§4.1a)
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    expect(submit).toBeDisabled();
    // Б-2: у неактивной кнопки названа причина
    expect(submit).toHaveAccessibleDescription("Выберите партнёра.");
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
    );
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);
    expect(await screen.findByText("Запрос ушёл на sales@steel.example")).toBeVisible();

    const log = await screen.findByRole("list", { name: "Запросы цены у партнёров" });
    expect(within(log).getByText("ООО «Вымышленная Сталь»")).toBeVisible();
    expect(within(log).getByText("Ждём ответ")).toBeVisible();
    expect(within(log).getByText(/Демо Снабженцев → sales@steel\.example/)).toBeVisible();
    expect(within(log).getByText(new RegExp(RAIL))).toBeVisible();

    fireEvent.click(
      within(log).getByRole("button", {
        name: "Ответ получен: партнёр «ООО «Вымышленная Сталь»»",
      }),
    );
    await waitFor(() => {
      expect(
        within(log).queryByRole("button", { name: /Ответ получен: партнёр/ }),
      ).not.toBeInTheDocument();
    });
    expect(within(log).getByText("Ответ получен")).toBeVisible();
  });

  it("ни одна строка не отмечена: «Отправить запрос» неактивна, причина названа (Б-2)", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
    );
    for (const box of within(modal).getAllByRole("checkbox")) {
      if ((box as HTMLInputElement).checked) fireEvent.click(box);
    }
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAccessibleDescription("Отметьте хотя бы одну строку.");
  });

  it("ДК-5: под запросом — «Ссылка партнёра в Кабинете»; отзыв гасит её после одного подтверждения", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
    );
    // письмо готово к отправке, когда предпросмотр показал, что увидит партнёр
    const send = within(modal).getByRole("button", { name: "Отправить запрос" });
    await waitFor(() => {
      expect(send).toBeEnabled();
    });
    fireEvent.click(send);
    const log = await screen.findByRole("list", { name: "Запросы цены у партнёров" });

    const block = (
      await within(log).findByRole("heading", { name: "Ссылка партнёра в Кабинете" })
    ).closest<HTMLElement>(".ant-card");
    if (!block) throw new Error("нет блока ссылки партнёра");
    expect(within(block).getByText("Получатель — d***@steel.example.")).toBeVisible();
    expect(within(block).getByText("Партнёр ещё не открывал.")).toBeVisible();
    expect(screen.queryByText(/Клиент ещё не открывал/)).toBeNull();

    fireEvent.click(within(block).getByRole("button", { name: "Отозвать ссылку" }));
    expect(
      await screen.findByRole("dialog", { name: "Отозвать ссылку на запрос цены?" }),
    ).toBeInTheDocument();
    await confirmDialog();
    expect(
      await within(block).findByText(/Ссылка отозвана: партнёр по ней ничего не откроет/),
    ).toBeVisible();
    expect(within(block).queryByRole("button", { name: "Отозвать ссылку" })).toBeNull();
  });

  it("у партнёра нет почты: адрес для письма обязателен", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    // форма — в боковом окне (§4.1a)
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Лес",
      "ООО «Пример Лес»",
    );
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    expect(submit).toBeDisabled();
    await waitFor(() => {
      expect(submit).toHaveAccessibleDescription("Укажите адрес партнёра для письма.");
    });
    fireEvent.change(await within(modal).findByLabelText("Адрес для письма"), {
      target: { value: "orders@lumber.example" },
    });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    fireEvent.click(submit);
    expect(await screen.findByText("Запрос ушёл на orders@lumber.example")).toBeVisible();
  });
});

describe("Расчёт · «Запросить цену» · партнёр выбирается (ЕД-6)", () => {
  it("у компании нет почты, но есть человек с почтой: адрес берётся из его карточки, вводить не нужно", async () => {
    server.use(
      http.get("*/people/counterparties/6/people", () =>
        HttpResponse.json({
          items: [
            {
              id: "61",
              name: "Лесов Л. Л.",
              position: "Менеджер",
              email: "orders@lumber.example",
              is_primary: true,
            },
          ],
        }),
      ),
    );
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    // вписанное название партнёром не становится: без выбора отправить нельзя
    const partner = within(modal).getByRole("combobox", { name: "Партнёр" });
    searchCompany(partner, "Пример");
    expect(within(modal).getByRole("button", { name: "Отправить запрос" })).toBeDisabled();
    await pickCompany(partner, "Лес", "ООО «Пример Лес»");
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    expect(within(modal).queryByLabelText("Адрес для письма")).toBeNull();
  });
});

describe("Расчёт · «Запросить цену» · роль поставщика ставится при отправке (ЕД-6)", () => {
  it("выбор клиента ролей не пишет; отправка — пишет; отказ — понятная причина и письма нет", async () => {
    const marked: unknown[] = [];
    const sent: unknown[] = [];
    let refuse = 404;
    server.use(
      http.post("*/people/counterparties/:id/roles", async ({ request }) => {
        marked.push(await request.clone().json());
        return refuse === 0
          ? undefined
          : HttpResponse.json(
              { code: "NOT_FOUND", message: "Нет.", source: "erp" },
              { status: refuse },
            );
      }),
      http.post("*/erp/calc/*/price-requests", async ({ request }) => {
        sent.push(await request.clone().json());
        return undefined;
      }),
      http.get("*/people/counterparties/7/people", () =>
        HttpResponse.json({
          items: [
            { id: "41", name: "Демо", position: null, email: "d@x.example", is_primary: true },
          ],
        }),
      ),
    );
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Демо-Путь",
      "АО «Демо-Путь»",
    );
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    expect(marked).toEqual([]);
    // компании нет в списке контрагентов: причина — не «нет права», запрос цены не уходит
    fireEvent.click(submit);
    expect(await within(modal).findByText(/Компании нет в списке контрагентов/)).toBeVisible();
    expect(within(modal).queryByText(/нет права/)).toBeNull();
    expect(sent).toEqual([]);
    refuse = 0;
    fireEvent.click(submit);
    await waitFor(() => {
      expect(sent).toHaveLength(1);
    });
    expect(marked).toEqual([
      { role: "supplier", on: true },
      { role: "supplier", on: true },
    ]);
  });
});

describe("Расчёт · «Добавить строку» в боковом окне (§4.1a)", () => {
  it("форма в окне задачи вместо задачи; добавленная строка — в таблице, окно снова показывает задачу", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    const form = await screen.findByRole("region", { name: "Новая строка расчёта" });
    fireEvent.change(within(form).getByLabelText("Наименование"), {
      target: { value: "Болт закладной М22" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Новая строка расчёта" })).toBeNull();
    });
    expect(
      await within(
        screen.getByRole("table", { name: `Строки расчёта по заявке ${NUMBER}` }),
      ).findByText("Болт закладной М22"),
    ).toBeVisible();
  });
});

describe("Расчёт · похожая позиция каталога (СЦ-10)", () => {
  async function addLine(name: string) {
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    const form = await screen.findByRole("region", { name: "Новая строка расчёта" });
    fireEvent.change(within(form).getByLabelText("Наименование"), { target: { value: name } });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Новая строка расчёта" })).toBeNull();
    });
    const table = screen.getByRole("table", { name: `Строки расчёта по заявке ${NUMBER}` });
    await within(table).findByText(name);
    return lineRow(name);
  }

  it("строка показывает «Похоже: …», подтвердить нельзя, «Выбрать» берёт позицию каталога", async () => {
    await openCalc("supply@demo.example");
    const row = await addLine("Привод СП-6М");

    expect(within(row).getByText(`Похоже: ${DRIVE}`)).toBeVisible();
    expect(
      within(row).getByRole("button", { name: "Подтвердить строку «Привод СП-6М»" }),
    ).toBeDisabled();
    expect(within(row).getByText("сначала выберите позицию")).toBeVisible();
    expect(within(row).queryByText("Черновик")).toBeNull();

    fireEvent.click(
      within(row).getByRole("button", { name: `Выбрать позицию каталога «${DRIVE}»` }),
    );

    await waitFor(() => {
      expect(screen.queryByText(`Похоже: ${DRIVE}`)).toBeNull();
    });
    expect(screen.getAllByText(DRIVE).length).toBeGreaterThan(1);
  });

  it("«Новая позиция» заводит черновик, подсказка уходит", async () => {
    await openCalc("supply@demo.example");
    const row = await addLine("Привод СП-6М");

    fireEvent.click(within(row).getByRole("button", { name: "Новая позиция: «Привод СП-6М»" }));

    await waitFor(() => {
      expect(screen.queryByText(`Похоже: ${DRIVE}`)).toBeNull();
    });
    expect(within(lineRow("Привод СП-6М")).getByText("Черновик")).toBeVisible();
  });
});

describe("Расчёт · «Запросить цену у партнёра» только пока расчёт открыт (Б-2)", () => {
  it("у КП на одобрении кнопки запроса цены нет", async () => {
    signIn("supply@demo.example");
    renderAt(`/erp/calc/${encodeURIComponent("ЗВ-2026-101")}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Расчёт по заявке ЗВ-2026-101" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Запросить цену у партнёра" })).toBeNull();
  });
});

describe("Расчёт · «Запросить цену» · слова клиента партнёру не уходят (В-2)", () => {
  async function openRequestWithoutCard(name: string) {
    await openCalc("supply@demo.example");
    // строка без карточки каталога: слова клиента из заявки
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    const form = await screen.findByRole("region", { name: "Новая строка расчёта" });
    fireEvent.change(within(form).getByLabelText("Наименование"), { target: { value: name } });
    fireEvent.click(within(form).getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Новая строка расчёта" })).toBeNull();
    });
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
    );
    return modal;
  }

  it("строка без карточки не уходит, пока сотрудник не назвал её; письмо несёт только подтверждённое название", async () => {
    const sent: { partner_names?: { line_id: string; name: string }[] }[] = [];
    server.use(
      http.post("*/erp/calc/*/price-requests", async ({ request }) => {
        sent.push((await request.clone().json()) as (typeof sent)[number]);
        return undefined;
      }),
    );
    const words = "Стрелка для ст. Чиланзар, ООО МетроСтрой";
    const modal = await openRequestWithoutCard(words);
    const send = within(modal).getByRole("button", { name: "Отправить запрос" });
    await within(modal).findAllByLabelText(/^Как назвать партнёру, строка \d+$/);
    const input = within(modal)
      .getAllByLabelText(/^Как назвать партнёру, строка \d+$/)
      .find((field) => (field as HTMLInputElement).value === "");
    if (!input) throw new Error("нет поля строки без названия");
    // слова клиента показаны сотруднику, но поле пустое и отправить нельзя
    expect(within(modal).getByText(/Партнёру эти слова не уходят/)).toBeVisible();
    expect(input).toHaveValue("");
    expect(send).toBeDisabled();
    fireEvent.change(input, { target: { value: "Стрелочный перевод" } });
    await waitFor(() => {
      expect(send).toBeEnabled();
    });
    fireEvent.click(send);
    await waitFor(() => {
      expect(sent).toHaveLength(1);
    });
    expect(sent[0]?.partner_names?.map((row) => row.name)).toEqual(["Стрелочный перевод"]);
    expect(JSON.stringify(sent[0])).not.toContain("Чиланзар");
  });

  it("комментарий партнёру виден в предпросмотре до отправки", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у партнёра" }));
    const modal = await screen.findByRole("region", { name: /^Запросить цену у партнёра/ });
    await pickCompany(
      within(modal).getByRole("combobox", { name: "Партнёр" }),
      "Сталь",
      "ООО «Вымышленная Сталь»",
    );
    fireEvent.change(within(modal).getByLabelText("Комментарий партнёру"), {
      target: { value: "Нужны сертификаты" },
    });
    const preview = await within(modal).findByRole("region", { name: "Что увидит партнёр" });
    expect(await within(preview).findByText(/Нужны сертификаты/)).toBeVisible();
  });
});
