import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { BodyEditor } from "./BodyEditor";
import { type BodyNode, paragraphOf, toBody } from "./bodyModel";

import "../../i18n";

let last: BodyNode | null = null;

function Harness({ initial }: { initial: BodyNode }) {
  const [value, setValue] = useState(initial);
  return (
    <BodyEditor
      id="body"
      label="Текст письма"
      value={value}
      onChange={(next) => {
        last = next;
        setValue(next);
      }}
    />
  );
}

describe("BodyEditor (Tiptap, план 2026-11-12 п. 1.2)", () => {
  it("показывает документ оформленным: заголовок, абзац; поле подписано для скринридера", async () => {
    render(
      <Harness
        initial={{
          type: "doc",
          content: [
            { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Сведения" }] },
            paragraphOf("Сообщаем следующее."),
          ],
        }}
      />,
    );
    const box = await screen.findByRole("textbox", { name: "Текст письма" });
    expect(within(box).getByRole("heading", { name: "Сведения" })).toBeInTheDocument();
    expect(within(box).getByText("Сообщаем следующее.")).toBeInTheDocument();
    const toolbar = screen.getByRole("toolbar", { name: "Оформление текста" });
    expect(
      within(toolbar)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual([
      "Заголовок",
      "Жирный",
      "Курсив",
      "Подчёркнутый",
      "Список",
      "Нумерованный список",
      "Таблица",
      "Ссылка",
    ]);
  });

  it("«Таблица» вставляет таблицу с шапкой — в теле она по схеме контракта", async () => {
    last = null;
    render(<Harness initial={{ type: "doc", content: [paragraphOf("Итоги")] }} />);
    await screen.findByRole("textbox", { name: "Текст письма" });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Таблица" }));
    });
    const emitted = (last as BodyNode | null)?.content ?? [];
    const inserted = emitted.find((node) => node.type === "table");
    expect(inserted?.content?.[0]?.content?.[0]?.type).toBe("tableHeader");
    // В тело таблица попадает по схеме контракта: вид «сетка», без служебных атрибутов редактора
    const header = inserted?.content?.[0]?.content?.[0];
    if (header) header.content = [paragraphOf("Счёт")];
    const table = (toBody(last as unknown as BodyNode, "ru").doc["content"] as BodyNode[]).find(
      (node) => node.type === "table",
    );
    expect(table?.attrs).toEqual({ variant: "grid" });
    expect(table?.content?.[0]?.content?.[0]).toEqual({
      type: "tableHeader",
      content: [paragraphOf("Счёт")],
    });
    expect(screen.getByRole("group", { name: "Таблица" })).toBeInTheDocument();
  });
});
