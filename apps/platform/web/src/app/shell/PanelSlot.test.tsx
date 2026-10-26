import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PanelPortal, PanelSlotProvider } from "./PanelSlot";
import { usePanelSlotHost } from "./panelSlotContext";

type Layout = "column" | "drawer" | "none";

/** Каркас в миниатюре: окно — колонка справа или Drawer (другой элемент), или его нет совсем (перестройка, закрыто). */
function Shell({ layout, tab }: { layout: Layout; tab: string }) {
  const { attach } = usePanelSlotHost(tab);
  if (layout === "none") return null;
  // Разные ветки разметки, как у каркаса: колонка и Drawer — разные элементы окна.
  return layout === "column" ? (
    <aside aria-label="Колонка">
      <div ref={attach} />
    </aside>
  ) : (
    <div role="dialog" aria-label="Drawer">
      <div ref={attach} />
    </div>
  );
}

/** Форма в боковом окне: несохранённое — в её собственном состоянии (как у формы приглашения). */
function Draft() {
  const [draft, setDraft] = useState("");
  return (
    <label>
      Имя
      <input
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
      />
    </label>
  );
}

function Page() {
  return (
    <PanelPortal tab="card">
      <Draft />
    </PanelPortal>
  );
}

function App({ layout, tab = "card" }: { layout: Layout; tab?: string }) {
  return (
    <PanelSlotProvider>
      <Shell layout={layout} tab={tab} />
      <Page />
    </PanelSlotProvider>
  );
}

describe("PanelPortal (R3-D-4)", () => {
  it("смена колонки на Drawer и обратно не теряет несохранённое", () => {
    const view = render(<App layout="column" />);
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Демо Новый" } });

    view.rerender(<App layout="drawer" />);
    expect(screen.getByRole("dialog", { name: "Drawer" })).toContainElement(
      screen.getByLabelText("Имя"),
    );
    expect(screen.getByLabelText("Имя")).toHaveValue("Демо Новый");

    view.rerender(<App layout="none" />);
    expect(screen.queryByLabelText("Имя")).toBeNull(); // окна нет — содержимого в документе нет

    view.rerender(<App layout="column" />);
    expect(screen.getByRole("complementary", { name: "Колонка" })).toContainElement(
      screen.getByLabelText("Имя"),
    );
    expect(screen.getByLabelText("Имя")).toHaveValue("Демо Новый");
  });

  it("неактивная вкладка — содержимого нет", () => {
    render(<App layout="column" tab="today" />);

    expect(screen.queryByLabelText("Имя")).toBeNull();
  });
});
