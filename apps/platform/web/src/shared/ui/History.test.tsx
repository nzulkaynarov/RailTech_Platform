import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { History } from "./History";

describe("History", () => {
  const items = [
    { state: "done", title: "Редакция согласована", meta: "25.10 · Рустамов А.К." },
    { state: "waiting", title: "Ждёт скан" },
    { state: "todo", title: "Счёт на предоплату" },
  ] as const;

  it("список с именем; состояние названо словом, а не только точкой", () => {
    renderUi(<History label="История договора" items={items} />);
    const list = screen.getByRole("list", { name: "История договора" });
    const rows = list.querySelectorAll("li");
    expect(rows[0]).toHaveTextContent("Сделано: Редакция согласована");
    expect(rows[1]).toHaveTextContent("Ожидается: Ждёт скан");
    expect(rows[2]).toHaveTextContent("Не начато: Счёт на предоплату");
    expect(screen.getByText("25.10 · Рустамов А.К.")).toBeVisible();
  });

  it("точки: форма и класс по состоянию, сами точки скрыты от скринридера", () => {
    renderUi(<History items={items} />);
    const dots = document.querySelectorAll(".pf-history-dot");
    expect(dots[0]).toHaveClass("pf-history-dot--done");
    expect(dots[0]?.querySelector("svg")).not.toBeNull();
    expect(dots[1]).toHaveClass("pf-history-dot--waiting");
    expect(dots[2]).toHaveClass("pf-history-dot--todo");
    dots.forEach((dot) => {
      expect(dot).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("слова состояний по языку", () => {
    renderUi(<History items={items} />, { language: "en" });
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Done: Редакция согласована");
  });
});
