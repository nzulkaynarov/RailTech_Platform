import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataBlock, ListSkeleton } from "./DataBlock";

describe("DataBlock (UX-1c, инвариант 6)", () => {
  it("busy — aria-busy без смены содержимого; без загрузки признака нет", () => {
    const { rerender, container } = render(
      <DataBlock busy>
        <p>Строки</p>
      </DataBlock>,
    );
    const block = container.querySelector(".pf-data-block");
    expect(block).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Строки")).toBeInTheDocument();
    rerender(
      <DataBlock>
        <p>Строки</p>
      </DataBlock>,
    );
    expect(block).not.toHaveAttribute("aria-busy");
  });

  it("новый ключ данных — список строится заново, фокус остаётся на «той же» кнопке под ним", () => {
    const { rerender } = render(
      <DataBlock resetKey="a">
        <button type="button">Дальше</button>
      </DataBlock>,
    );
    const first = screen.getByRole("button", { name: "Дальше" });
    first.focus();
    rerender(
      <DataBlock resetKey="b">
        <button type="button">Дальше</button>
      </DataBlock>,
    );
    const second = screen.getByRole("button", { name: "Дальше" });
    expect(second).not.toBe(first);
    expect(second).toHaveFocus();
  });

  it("скелетон первой загрузки — строки по размеру страницы, но не больше 10, с меткой для удержания высоты", () => {
    const { container, rerender } = render(<ListSkeleton rows={25} />);
    expect(container.querySelectorAll(".pf-list-skel-row")).toHaveLength(10);
    expect(container.querySelector("[data-pf-skeleton]")).toHaveAttribute("aria-hidden", "true");
    rerender(<ListSkeleton rows={3} />);
    expect(container.querySelectorAll(".pf-list-skel-row")).toHaveLength(3);
  });
});
