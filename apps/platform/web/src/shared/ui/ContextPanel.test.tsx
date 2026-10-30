import { fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { ContextPanel, ContextPanelDrawer } from "./ContextPanel";

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
    // обёртка остаётся в документе (цель aria-controls кнопки «Панель»), но скрыта — и от скринридера
    expect(document.getElementById("ctx")).not.toBeVisible();
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("булавка и порог ширины меняют только класс: вкладки и форма окна не пересоздаются (UX-1a, S4)", () => {
    function Harness() {
      const [docked, setDocked] = useState(false);
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setDocked((value) => !value);
            }}
          >
            Порог
          </button>
          <ContextPanel
            open
            docked={docked}
            panelMode={docked ? "docked" : "overlay"}
            id="ctx"
            label="Боковое окно"
            hideLabel="Скрыть боковое окно"
            tabs={TABS}
            activeTab="approval"
            onTabChange={() => undefined}
            onHide={() => undefined}
          >
            <input aria-label="Комментарий" />
          </ContextPanel>
        </>
      );
    }
    renderUi(<Harness />);
    const region = screen.getByRole("complementary", { name: "Боковое окно" });
    const field = screen.getByRole("textbox", { name: "Комментарий" });
    fireEvent.change(field, { target: { value: "черновик" } });
    expect(region).toHaveClass("pf-panel-overlay");

    fireEvent.click(screen.getByRole("button", { name: "Порог" }));
    expect(region).toHaveClass("pf-panel-docked");
    expect(region).not.toHaveClass("pf-panel-overlay");
    expect(screen.getByRole("complementary", { name: "Боковое окно" })).toBe(region);
    expect(screen.getByRole("textbox", { name: "Комментарий" })).toBe(field);
    expect(field).toHaveValue("черновик");
  });

  function duplicateIds(root: ParentNode): string[] {
    const ids = Array.from(root.querySelectorAll("[id]")).map((el) => el.id);
    return ids.filter((id, index) => ids.indexOf(id) !== index);
  }

  it("все id внутри бокового окна уникальны", () => {
    const { container } = renderUi(panel(true));
    expect(container.querySelectorAll("[id]").length).toBeGreaterThan(1);
    expect(duplicateIds(container)).toEqual([]);
    // id корня окна не повторяется во вложенных вкладках; вкладки — под `<id>-tabs`
    expect(container.querySelectorAll("#ctx")).toHaveLength(1);
    expect(container.querySelector("#ctx-tabs-tab-approval")).not.toBeNull();
  });

  it("поверх таблицы (overlay): немодальная область без aria-modal, Esc внутри закрывает", () => {
    const onHide = vi.fn();
    renderUi(
      <ContextPanel
        open
        panelMode="overlay"
        id="ctx"
        label="Боковое окно"
        hideLabel="Скрыть боковое окно"
        tabs={TABS}
        activeTab="approval"
        onTabChange={() => undefined}
        onHide={onHide}
      >
        <p>Содержимое вкладки</p>
      </ContextPanel>,
    );
    const region = screen.getByRole("complementary", { name: "Боковое окно" });
    expect(region).toHaveClass("pf-panel-overlay");
    expect(document.querySelector("[aria-modal]")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Одобрение" }), { key: "Escape" });
    expect(onHide).toHaveBeenCalledOnce();
  });

  it("Esc вне бокового окна его не закрывает", () => {
    const onHide = vi.fn();
    renderUi(panel(true, { onHide }));
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onHide).not.toHaveBeenCalled();
  });

  it("все id уникальны и в варианте Drawer", () => {
    renderUi(
      <ContextPanelDrawer
        open
        onClose={() => undefined}
        offsetTop={56}
        offsetBottom={0}
        id="ctx"
        label="Боковое окно"
        hideLabel="Скрыть боковое окно"
        tabs={TABS}
        activeTab="approval"
        onTabChange={() => undefined}
        onHide={() => undefined}
      >
        <p>Содержимое вкладки</p>
      </ContextPanelDrawer>,
    );
    expect(duplicateIds(document.body)).toEqual([]);
    expect(document.body.querySelectorAll("#ctx")).toHaveLength(1);
    expect(document.body.querySelector("#ctx-tabs-tab-approval")).not.toBeNull();
  });
});
