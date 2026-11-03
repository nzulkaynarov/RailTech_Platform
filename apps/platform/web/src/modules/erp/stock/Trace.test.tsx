import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { fillDate } from "../../../test/fields";
import { parseSerials, traceProblem } from "./trace";

setupCalcTests();

const MOTOR = "Электродвигатель асинхронный АИР-100";
const ORDER = `ЗП-${String(new Date().getFullYear())}-028`;
const nextYear = `${String(new Date().getFullYear() + 1)}-06-30`;

async function receiveMotors(serials: string) {
  signIn("supply@demo.example");
  renderAt(`/erp/stock/${encodeURIComponent(ORDER)}`);
  fireEvent.click(await screen.findByRole("button", { name: "Принять товар" }));
  const modal = await screen.findByRole("dialog");
  const fields = within(
    await within(modal).findByRole("group", { name: `Номера и документ: «${MOTOR}»` }),
  );
  fireEvent.change(fields.getByLabelText("Серийные номера — по одному в строке"), {
    target: { value: serials },
  });
  return { modal, fields };
}

/** L0-3, ADR-0021: серийные и документ на приёмке, выбор единиц на отгрузке, поиск «откуда и куда». */
describe("Склад · прослеживаемость", () => {
  it("вставка столбца разбирается по строкам, запятым и табуляции; проверка до отправки", () => {
    expect(parseSerials(" ENG-1\nENG-2, ENG-3;\tENG-4 \n\n")).toEqual([
      "ENG-1",
      "ENG-2",
      "ENG-3",
      "ENG-4",
    ]);
    const serial = { tracking: "serial", requires_doc: false } as const;
    const draft = { serials: "A\nA", lot: "", expiry: "", docNumber: "", docValidUntil: "" };
    expect(traceProblem(serial, draft, 1)).toBe("serials");
    expect(traceProblem(serial, draft, 2)).toBe("serialsRepeat");
    expect(traceProblem({ tracking: "none", requires_doc: false }, draft, 5)).toBeNull();
  });

  it("товар «только количество» — на приёмке ничего нового", async () => {
    signIn("supply@demo.example");
    renderAt(`/erp/stock/${encodeURIComponent(`ЗП-${String(new Date().getFullYear())}-029`)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Принять товар" }));
    const modal = await screen.findByRole("dialog");
    await within(modal).findByRole("spinbutton", { name: /Принять/ });
    expect(within(modal).queryByLabelText("Серийные номера — по одному в строке")).toBeNull();
    expect(within(modal).queryByLabelText("№ сертификата или декларации")).toBeNull();
  });

  it("приёмка серийных: число номеров = количеству, документ обязателен; затем отгрузка и поиск", async () => {
    const { modal, fields } = await receiveMotors("ENG-0001");
    expect(fields.getByText("Введено 1 из 2")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    expect(
      await within(modal).findByText(
        `«${MOTOR}»: серийных номеров должно быть столько, сколько принимаете.`,
      ),
    ).toBeInTheDocument();

    fireEvent.change(fields.getByLabelText("Серийные номера — по одному в строке"), {
      target: { value: "ENG-0001\nENG-0002" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    expect(await within(modal).findByText(/укажите № сертификата/)).toBeInTheDocument();
    fireEvent.change(fields.getByLabelText("№ сертификата или декларации"), {
      target: { value: "ЕАЭС RU С-UZ.ДЕМО.В.00042" },
    });
    fillDate(fields.getByLabelText("Действует до"), nextYear);
    fireEvent.click(within(modal).getByRole("button", { name: "Принять" }));
    expect(await screen.findByText("Товар принят")).toBeVisible();

    // отгрузка: без выбора серийных не уходит, с выбором — номер в накладной
    renderAt("/erp/stock?view=shipments");
    fireEvent.change(await screen.findByRole("searchbox", { name: "Номер проекта" }), {
      target: { value: "ПР-2026-099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Найти резервы" }));
    const qty = await screen.findByRole("spinbutton", { name: `Отгрузить, «${MOTOR}»` });
    fireEvent.change(qty, { target: { value: "1" } });
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Отгрузить, «Скрепление рельсовое КБ-65»" }),
      { target: { value: "0" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Отгрузить" }));
    expect(
      await screen.findByText(`«${MOTOR}»: выберите серийные номера или партии на всё количество.`),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "ENG-0002" }));
    fireEvent.click(screen.getByRole("button", { name: "Отгрузить" }));
    expect(await screen.findByText(/Отгружено, накладная ОТГ-\d{4}-001/)).toBeVisible();
    const table = within(await screen.findByRole("table", { name: "Отгрузки по проектам" }));
    expect(table.getByText("ENG-0002")).toBeVisible();

    // поиск по серийному: откуда и куда
    renderAt("/erp/stock?view=trace&q=ENG-0002");
    const card = (await screen.findByRole("heading", { name: /Серийный ENG-0002/ })).closest(
      ".ant-card",
    ) as HTMLElement;
    const from = within(within(card).getByRole("region", { name: "Откуда" }));
    expect(from.getByText("ООО «Вымышленная Сталь»")).toBeVisible();
    expect(from.getByText(ORDER)).toBeVisible();
    expect(from.getByText("Завод «Вымышленный Электро»")).toBeVisible();
    expect(from.getByText(/ЕАЭС RU С-UZ\.ДЕМО\.В\.00042/)).toBeVisible();
    const to = within(within(card).getByRole("region", { name: "Куда" }));
    expect(to.getByText(/ОТГ-\d{4}-001/)).toBeVisible();
    expect(to.getByText("ПР-2026-099")).toBeVisible();
    expect(within(card).getByText("Отгружен")).toBeVisible();
    await waitFor(() => {
      expect(screen.getByRole("searchbox", { name: "Серийный номер или партия" })).toHaveValue(
        "ENG-0002",
      );
    });
  });

  it("поиск без совпадений говорит словами", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/stock?view=trace&q=НЕТ-ТАКОГО");
    expect(await screen.findByText("Ничего не нашли")).toBeVisible();
  });
});
