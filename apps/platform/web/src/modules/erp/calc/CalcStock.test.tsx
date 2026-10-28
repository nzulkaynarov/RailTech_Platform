import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

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
      screen.queryByRole("button", { name: "Запросить цену у поставщика" }),
    ).not.toBeInTheDocument();
  });
});

describe("Расчёт · «Запросить цену у поставщика»", () => {
  it("письмо поставщику и запись в журнале: кто, когда, кому, по каким строкам; «Ответ получен»", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у поставщика" }));
    const modal = await screen.findByRole("dialog");
    expect(within(modal).getByText("Что произойдёт")).toBeInTheDocument();
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    expect(submit).toBeDisabled();
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Поставщик" }));
    fireEvent.click(
      await screen.findByText(/ООО «Вымышленная Сталь» · sales@steel\.example/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(await screen.findByText("Запрос ушёл на sales@steel.example")).toBeVisible();

    const log = await screen.findByRole("list", { name: "Запросы цены у поставщиков" });
    expect(within(log).getByText("ООО «Вымышленная Сталь»")).toBeVisible();
    expect(within(log).getByText("Ждём ответ")).toBeVisible();
    expect(within(log).getByText(/Демо Снабженцев → sales@steel\.example/)).toBeVisible();
    expect(within(log).getByText(new RegExp(RAIL))).toBeVisible();

    fireEvent.click(
      within(log).getByRole("button", {
        name: "Ответ получен: поставщик «ООО «Вымышленная Сталь»»",
      }),
    );
    await waitFor(() => {
      expect(
        within(log).queryByRole("button", { name: /Ответ получен: поставщик/ }),
      ).not.toBeInTheDocument();
    });
    expect(within(log).getByText("Ответ получен")).toBeVisible();
  });

  it("у поставщика нет почты: адрес для письма обязателен", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(screen.getByRole("button", { name: "Запросить цену у поставщика" }));
    const modal = await screen.findByRole("dialog");
    fireEvent.mouseDown(within(modal).getByRole("combobox", { name: "Поставщик" }));
    fireEvent.click(
      await screen.findByText(/ООО «Пример Лес» · нет почты/, {
        selector: ".ant-select-item-option-content",
      }),
    );
    const submit = within(modal).getByRole("button", { name: "Отправить запрос" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(modal).getByLabelText("Адрес для письма"), {
      target: { value: "orders@lumber.example" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(await screen.findByText("Запрос ушёл на orders@lumber.example")).toBeVisible();
  });
});
