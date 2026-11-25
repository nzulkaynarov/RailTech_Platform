import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const IN_WORK = "ЗВ-2026-097";
const AT_DIRECTOR = "ЗВ-2026-101";
const path = (number: string) => `/erp/calc/${encodeURIComponent(number)}?parse=1`;

async function heading(number: string) {
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${number}` }),
  ).toBeVisible();
}

describe("«Создать · Расчёт»: разбор заявки (Б-6)", () => {
  it("расчёт в работе: `?parse=1` открывает «Разбор заявки»", async () => {
    signIn("universal@demo.example");
    renderAt(path(IN_WORK));
    await heading(IN_WORK);
    expect(await screen.findByRole("dialog", { name: "Разбор заявки" })).toBeVisible();
  });

  it("КП у директора: разбор не открывается — строки не правятся", async () => {
    signIn("universal@demo.example");
    renderAt(path(AT_DIRECTOR));
    await heading(AT_DIRECTOR);
    expect(screen.queryByRole("dialog", { name: "Разбор заявки" })).toBeNull();
  });
});

describe("«Создать · Расчёт»: список заявок (Б-6)", () => {
  it("стрелка строки ведёт в расчёт с разбором, как и номер", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/requests?new=calc");
    const arrow = await screen.findByRole("link", { name: `Открыть расчёт по заявке ${IN_WORK}` });
    expect(arrow).toHaveAttribute("href", `/erp/calc/${encodeURIComponent(IN_WORK)}?parse=1`);
  });

  it("«Все заявки в расчёте» при пустом «Мои» не теряет путь «Создать · Расчёт»", async () => {
    signIn("accountant@demo.example");
    renderAt("/erp/requests?mine=1&new=calc");
    const all = await screen.findByRole("link", { name: "Все заявки в расчёте" });
    expect(all).toHaveAttribute("href", "/erp/requests?new=calc");
    await waitFor(() => {
      expect(within(document.body).getByText(/Выберите заявку/)).toBeVisible();
    });
  });
});
