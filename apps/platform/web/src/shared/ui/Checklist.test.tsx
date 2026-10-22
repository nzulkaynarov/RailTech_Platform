import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { Checklist } from "./Checklist";

describe("Checklist", () => {
  const items = [
    { state: "ok", label: "Виза снабженца", meta: "Азиз · 22.10" },
    { state: "fail", label: "Маржа ниже 22 %" },
    { state: "pending", label: "Срок клиента выдержан" },
  ] as const;

  it("каждая строка — со словом состояния для скринридера и без опоры на цвет", () => {
    renderUi(<Checklist label="Проверка перед отправкой" items={items} />);
    const rows = screen
      .getByRole("list", { name: "Проверка перед отправкой" })
      .querySelectorAll("li");
    expect(rows[0]).toHaveTextContent("Выполнено: Виза снабженца");
    expect(rows[1]).toHaveTextContent("Не выполнено: Маржа ниже 22 %");
    expect(rows[2]).toHaveTextContent("Ожидает: Срок клиента выдержан");
  });

  it("значок — разные формы (галочка, крестик, тире), скрыт от скринридера", () => {
    renderUi(<Checklist items={items} />);
    const chips = document.querySelectorAll(".pf-check-chip");
    const paths = Array.from(chips).map((chip) => chip.querySelector("path")?.getAttribute("d"));
    expect(new Set(paths).size).toBe(3);
    chips.forEach((chip) => {
      expect(chip).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("дата и автор справа", () => {
    renderUi(<Checklist items={items} />);
    expect(screen.getByText("Азиз · 22.10")).toBeVisible();
  });
});
