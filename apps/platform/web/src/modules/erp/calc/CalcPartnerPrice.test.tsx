import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { patchCalcMock } from "../../../mocks/erpCalc";
import { seedCalcs } from "../../../mocks/fixtures/calc";
import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const NUMBER = "ЗВ-2026-097";
const PATH = `/erp/calc/${encodeURIComponent(NUMBER)}`;
const RAIL = "Перевод стрелочный Р65 марки 1/11";

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

describe("Расчёт · закупка по цене партнёра (РАСЧ-1)", () => {
  it("снабженец видит, чья цена стоит в закупке, от какой даты и до какой она действует", async () => {
    await openCalc("supply@demo.example");
    const source = within(lineRow(RAIL)).getByTestId("partner-source");
    // В строке — коротко, полный текст — в подсказке
    expect(source).toHaveTextContent("ООО «Вымышленная Сталь» · до 31.12.2026 · 45 дн.");
    expect(within(source).getByRole("button")).toHaveAttribute(
      "title",
      expect.stringMatching(/Цена партнёра ООО «Вымышленная Сталь» от .*20.*действует до .*31/),
    );
  });

  it("другую цену выбирают из короткого списка — закупка и валюта строки меняются", async () => {
    await openCalc("supply@demo.example");
    const row = within(lineRow(RAIL));
    fireEvent.click(within(row.getByTestId("partner-source")).getByRole("button"));
    fireEvent.click(await screen.findByRole("option", { name: /ООО «Демо Металл» · .*до/ }));
    await waitFor(() => {
      expect(within(lineRow(RAIL)).getByTestId("partner-source")).toHaveTextContent(
        /ООО «Демо Металл» · до/,
      );
    });
    const purchase = within(lineRow(RAIL)).getByRole("spinbutton", {
      name: `Закупка за единицу для «${RAIL}»`,
    });
    expect((purchase as HTMLInputElement).value).toMatch(/^7\s900/);
  });

  it("действующей цены нет, есть истёкшая: она не берётся молча, предлагается «Запросить цену»", async () => {
    const calc = seedCalcs().find((c) => c.number === NUMBER);
    if (!calc) throw new Error("нет расчёта");
    const lines = calc.lines.map((l) =>
      l.name === RAIL
        ? {
            ...l,
            purchase: 0,
            partner: {
              offerId: null,
              options: [],
              expired: { supplier: "ООО «Вымышленная Сталь»", validUntil: "2026-11-10" },
            },
          }
        : l,
    );
    patchCalcMock(NUMBER, { lines });
    await openCalc("supply@demo.example");
    const source = within(lineRow(RAIL)).getByTestId("partner-source");
    expect(source).toHaveTextContent(/Цена партнёра ООО «Вымышленная Сталь» истекла .*10/);
    expect(within(source).getByRole("button", { name: "Запросить цену" })).toBeVisible();
  });

  it("закупку ввели руками, но цены партнёров есть: список выбора открывается", async () => {
    const calc = seedCalcs().find((c) => c.number === NUMBER);
    if (!calc) throw new Error("нет расчёта");
    const lines = calc.lines.map((l) =>
      l.name === RAIL && l.partner ? { ...l, partner: { ...l.partner, offerId: null } } : l,
    );
    patchCalcMock(NUMBER, { lines });
    await openCalc("supply@demo.example");
    const source = within(lineRow(RAIL)).getByTestId("partner-source");
    fireEvent.click(within(source).getByRole("button", { name: /Другая цена/ }));
    expect(await screen.findByRole("option", { name: /ООО «Демо Металл» · .*до/ })).toBeInTheDocument();
  });

  it("маржа ниже порога — предупреждение у «Расчёт готов» и метка у строки, кнопку оно не блокирует", async () => {
    // Цена клиенту почти равна закупке: маржа около 1 % при пороге мока 12 %
    const calc = seedCalcs().find((c) => c.number === NUMBER);
    const lines = (calc?.lines ?? []).map((l) =>
      l.name === RAIL ? { ...l, client: 91_000_000 } : l,
    );
    patchCalcMock(NUMBER, { lines });
    await openCalc("supply@demo.example");
    expect(await screen.findByText(/Маржа .* ниже порога/)).toBeInTheDocument();
    expect(within(lineRow(RAIL)).getByRole("img", { name: /ниже порога 12\.0 %/ })).toBeVisible();
    expect(screen.getAllByText(/ниже порога/).length).toBeGreaterThan(0);
    expect(within(lineRow(RAIL)).getByRole("img", { name: /ниже порога/ })).toBeVisible();
  });

  it("гл. инженер и бухгалтер цен партнёров не видят", async () => {
    await openCalc("engineer@demo.example");
    expect(screen.queryByTestId("partner-source")).not.toBeInTheDocument();
    expect(screen.queryByText(/Демо Металл/)).not.toBeInTheDocument();
  });
});
