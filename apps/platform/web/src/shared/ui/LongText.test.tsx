import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { LongText } from "./LongText";

const LONG = Array.from({ length: 40 }, (_, i) => `Строка запроса ${String(i + 1)}`).join("\n");

describe("LongText", () => {
  it("короткий текст — как есть, без кнопки", () => {
    renderUi(<LongText text="Нужен кабель" />);
    expect(screen.getByText("Нужен кабель")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("длинный текст свёрнут и раскрывается «Показать полностью»", () => {
    renderUi(<LongText text={LONG} />);
    const text = document.querySelector(".pf-long-text") as HTMLElement;
    expect(text).toHaveAttribute("data-clamped", "true");
    fireEvent.click(screen.getByRole("button", { name: "Показать полностью" }));
    expect(text).toHaveAttribute("data-clamped", "false");
    expect(screen.getByRole("button", { name: "Свернуть" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
