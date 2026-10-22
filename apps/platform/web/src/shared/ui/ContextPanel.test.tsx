import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { ContextPanel } from "./ContextPanel";

const TABS = [
  { key: "approval", label: "Одобрение" },
  { key: "chat", label: "Чат проекта" },
  { key: "docs", label: "Документы" },
];

function panel(
  open: boolean,
  extra: { onHide?: () => void; onTabChange?: (key: string) => void } = {},
) {
  return (
    <ContextPanel
      open={open}
      id="ctx"
      label="Боковое окно"
      hideLabel="Скрыть боковое окно"
      tabs={TABS}
      activeTab="approval"
      onTabChange={extra.onTabChange ?? (() => undefined)}
      onHide={extra.onHide ?? (() => undefined)}
    >
      <p>Содержимое вкладки</p>
    </ContextPanel>
  );
}

describe("ContextPanel", () => {
  it("открытое: область с именем, вкладки, панель вкладки и кнопка «Скрыть боковое окно» вне tablist", () => {
    renderUi(panel(true));
    expect(screen.getByRole("complementary", { name: "Боковое окно" })).toBeVisible();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Одобрение", "Чат проекта", "Документы"]);
    expect(screen.getByRole("tab", { name: "Одобрение" })).toHaveAttribute("aria-selected", "true");

    expect(screen.getByRole("tabpanel")).toHaveTextContent("Содержимое вкладки");
    const hide = screen.getByRole("button", { name: "Скрыть боковое окно" });
    expect(hide.closest("[role=tablist]")).toBeNull();
    expect(hide).toHaveStyle({ width: "28px", height: "28px" });
  });

  it("вкладка и кнопка сворачивания сообщают наверх", () => {
    const onHide = vi.fn();
    const onTabChange = vi.fn();
    renderUi(panel(true, { onHide, onTabChange }));
    fireEvent.click(screen.getByRole("tab", { name: "Чат проекта" }));
    expect(onTabChange).toHaveBeenCalledWith("chat");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть боковое окно" }));
    expect(onHide).toHaveBeenCalledOnce();
  });

  it("свёрнутое не рендерит содержимое и скрыто от скринридера", () => {
    renderUi(panel(false));
    expect(screen.queryByText("Содержимое вкладки")).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(document.getElementById("ctx")).toHaveAttribute("aria-hidden", "true");
  });
});
