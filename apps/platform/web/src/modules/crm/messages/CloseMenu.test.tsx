import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../../test/renderUi";
import { CloseMenu } from "./CloseMenu";

function setup() {
  renderUi(<CloseMenu lead="L-1" name="Азиз" close discard inline />);
  return screen.getByRole("button", { name: "Закрыть: Азиз" });
}

describe("CloseMenu inline: клавиатура и фокус", () => {
  it("раскрывается в потоке с aria-controls; Escape сворачивает и возвращает фокус на кнопку", async () => {
    const button = setup();
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    const menu = await screen.findByRole("menu");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", menu.id);
    const item = within(menu).getByRole("menuitem", { name: "Спам" });
    item.focus();
    fireEvent.keyDown(item, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("menu")).toBeNull();
    });
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("после выбора пункта и закрытия окна фокус возвращается на «Закрыть»", async () => {
    const button = setup();
    fireEvent.click(button);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Спам" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /Отмена|Отменить|Закрыть/ }));
    await waitFor(() => {
      expect(button).toHaveFocus();
    });
  });
});
