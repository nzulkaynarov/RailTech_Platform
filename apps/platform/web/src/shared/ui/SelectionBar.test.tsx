import { fireEvent, render, screen } from "@testing-library/react";
import { Button } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../i18n";
import { SelectionBar } from "./SelectionBar";

beforeEach(() => {
  void i18n.changeLanguage("ru");
});

describe("SelectionBar", () => {
  it("shows the count, the screen's actions and clears the selection", () => {
    const onClear = vi.fn();
    render(
      <SelectionBar count={3} label="Выбранные письма" onClear={onClear}>
        <Button>В архив</Button>
      </SelectionBar>,
    );
    const bar = screen.getByRole("region", { name: "Выбранные письма" });
    expect(bar).toHaveTextContent("Выбрано: 3");
    expect(screen.getByRole("button", { name: "В архив" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Снять выбор" }));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it("is hidden when nothing is selected", () => {
    render(
      <SelectionBar count={0} label="Выбранные письма" onClear={() => undefined}>
        <Button>В архив</Button>
      </SelectionBar>,
    );
    expect(screen.queryByRole("region", { name: "Выбранные письма" })).toBeNull();
  });
});
