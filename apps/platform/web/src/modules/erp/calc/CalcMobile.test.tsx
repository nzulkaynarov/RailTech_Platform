import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests(390);

describe("Расчёт по заявке на телефоне (B-020)", () => {
  it("строки — карточками; «Задание» — лист на весь экран с кнопкой «Закрыть»", async () => {
    signIn("engineer@demo.example");
    renderAt(`/erp/calc/${encodeURIComponent("ЗВ-2026-097")}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Расчёт по заявке ЗВ-2026-097" }),
    ).toBeVisible();
    expect(
      screen.getByRole("list", { name: "Строки расчёта по заявке ЗВ-2026-097" }),
    ).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Задание и визы" }));
    const sheet = await screen.findByRole("dialog", { name: "Задание" });
    expect(
      await within(sheet).findByText(/Посчитать переводы со склада и под заказ/),
    ).toBeVisible();
    expect(within(sheet).getByText("Визы по заявке")).toBeVisible();
    fireEvent.click(within(sheet).getByRole("button", { name: "Закрыть" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Задание" })).toBeNull();
    });
  });
});
