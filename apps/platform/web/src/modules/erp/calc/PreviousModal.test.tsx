import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupCalcTests, signIn } from "../../../test/calcKit";

setupCalcTests();

const NUMBER = "ЗВ-2026-103";
const PATH = `/erp/calc/${encodeURIComponent(NUMBER)}`;

describe("«Как в прошлой заявке» (план 1.5)", () => {
  it("снабженец копирует состав прошлого расчёта: строки своей зоны, об остальных — подсказка", async () => {
    signIn("supply@demo.example");
    renderAt(PATH);
    expect(
      await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();
    const start = screen.queryByRole("button", { name: "Начать расчёт" });
    if (start) {
      fireEvent.click(start);
      await screen.findByRole("button", { name: "Как в прошлой заявке" });
    }
    fireEvent.click(screen.getByRole("button", { name: "Как в прошлой заявке" }));
    const dialog = await screen.findByRole("dialog", { name: "Как в прошлой заявке" });
    const options = await within(dialog).findAllByRole("radio");
    expect(options.length).toBeGreaterThan(0);
    fireEvent.click(within(dialog).getByRole("radio", { name: /ЗВ-2026-097/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Скопировать состав" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Как в прошлой заявке" })).toBeNull();
    });
    expect(await screen.findByText(/^Строки добавлены/)).toBeVisible();
  });
});
