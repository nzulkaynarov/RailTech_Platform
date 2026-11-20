import { describe, expect, it } from "vitest";

import { pastedRows } from "./pasteRows";

describe("вставка из Excel (план 1.1)", () => {
  it("с шапкой: столбцы по названиям, количество с запятой — как написано (СЦ-10)", () => {
    const text = [
      "№\tНаименование\tАртикул\tКол-во\tЕд. изм.\tПримечание",
      "1\tБолт путевой М22\tБ-22\t400\tшт.\t",
      "2\tКлемма КБ-65\tКБ65\t12,5\tкомпл.\tсрочно",
    ].join("\n");
    expect(pastedRows(text)).toEqual([
      {
        name: "Болт путевой М22",
        quantity: 400,
        unit: "шт.",
        unit_code: "",
        article: "Б-22",
        note: "",
      },
      {
        name: "Клемма КБ-65",
        quantity: 12.5,
        unit: "компл.",
        unit_code: "",
        article: "КБ65",
        note: "срочно",
      },
    ]);
  });

  it("без шапки: название — длинный текст, количество — числовой столбец, единица — за ним", () => {
    const text = "Перевод стрелочный Р65 1/11\t2\tкомпл.\nШпала железобетонная\t300\tшт.";
    expect(pastedRows(text)).toEqual([
      {
        name: "Перевод стрелочный Р65 1/11",
        quantity: 2,
        unit: "компл.",
        unit_code: "",
        article: "",
        note: "",
      },
      {
        name: "Шпала железобетонная",
        quantity: 300,
        unit: "шт.",
        unit_code: "",
        article: "",
        note: "",
      },
    ]);
  });

  it("обычный текст — не таблица: уходит на ИИ-разбор", () => {
    expect(pastedRows("Нужны 2 стрелочных перевода Р65 и 300 шпал")).toBeNull();
    expect(pastedRows("")).toBeNull();
  });
});
