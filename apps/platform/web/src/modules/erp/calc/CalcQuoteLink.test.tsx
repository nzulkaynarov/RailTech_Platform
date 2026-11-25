import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { patchCalcMock } from "../../../mocks/erpCalc";
import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const AT_DIRECTOR = "ЗВ-2026-101";
const QUOTE_HREF = `/eds/drafts/${encodeURIComponent("КП-2026/112")}`;

async function openCalc(email: string, number: string) {
  signIn(email);
  renderAt(`/erp/calc/${encodeURIComponent(number)}`);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${number}` }),
  ).toBeVisible();
}

describe("Расчёт · после «Расчёт готов» есть путь дальше (Б-1)", () => {
  it("у КП на одобрении в плашке — ссылка на КП", async () => {
    await openCalc("universal@demo.example", AT_DIRECTOR);
    const link = await screen.findByRole("link", { name: "Открыть КП КП-2026/112" });
    expect(link).toHaveAttribute("href", QUOTE_HREF);
  });

  it("у одобренного КП вместо неактивной кнопки — «КП одобрено · Открыть проект»", async () => {
    patchCalcMock(AT_DIRECTOR, { state: "approved" });
    await openCalc("universal@demo.example", AT_DIRECTOR);
    expect(await screen.findByText(/^КП одобрено ·/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Расчёт готов" })).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть проект" })).toHaveAttribute(
      "href",
      `/eds/projects?q=${encodeURIComponent("КП-2026/112")}`,
    );
    expect(screen.getByRole("link", { name: "Открыть КП КП-2026/112" })).toHaveAttribute(
      "href",
      QUOTE_HREF,
    );
  });

  it("у отклонённого директором КП — «КП отклонено» и ссылка на КП, без пустой причины", async () => {
    patchCalcMock(AT_DIRECTOR, { state: "rejected", rejectedBy: "director" });
    await openCalc("universal@demo.example", AT_DIRECTOR);
    expect(await screen.findByText("КП отклонено")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Расчёт готов" })).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть КП КП-2026/112" })).toBeVisible();
  });
});
