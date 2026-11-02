import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import "../../i18n";
import { BodyEditor } from "./BodyEditor";
import { type Block, emptyBlocks } from "./bodyModel";

function Harness({ onBlocks }: { onBlocks: (blocks: Block[]) => void }) {
  const [value, setValue] = useState<Block[]>(emptyBlocks());
  return (
    <>
      <label htmlFor="body">Текст</label>
      <BodyEditor
        id="body"
        value={value}
        onChange={(next) => {
          setValue(next);
          onBlocks(next);
        }}
      />
    </>
  );
}

describe("BodyEditor", () => {
  it("абзац по подписи, добавить список и таблицу, переставить и удалить блок", () => {
    let last: Block[] = [];
    render(<Harness onBlocks={(b) => (last = b)} />);
    fireEvent.change(screen.getByLabelText("Текст"), { target: { value: "Сообщаем." } });

    const add = screen.getByRole("group", { name: "Добавить блок" });
    fireEvent.click(within(add).getByRole("button", { name: /Список/ }));
    fireEvent.change(screen.getByLabelText("Блок 2: Список"), {
      target: { value: "первое\nвторое" },
    });
    fireEvent.click(within(add).getByRole("button", { name: /Таблица/ }));
    fireEvent.change(screen.getByLabelText("Шапка, столбец 1"), { target: { value: "Счёт" } });
    fireEvent.change(screen.getByLabelText("Строка 1, столбец 2"), { target: { value: "14 400" } });
    fireEvent.click(screen.getByRole("button", { name: "+ столбец" }));
    expect(screen.getByLabelText("Шапка, столбец 3")).toBeInTheDocument();

    expect(last.map((b) => b.kind)).toEqual(["paragraph", "bullet", "table"]);
    expect(last[1]).toMatchObject({ items: ["первое", "второе"] });
    expect(last[2]).toMatchObject({
      rows: [
        ["Счёт", "", ""],
        ["", "14 400", ""],
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Выше: Блок 3: Таблица" }));
    expect(last.map((b) => b.kind)).toEqual(["paragraph", "table", "bullet"]);
    fireEvent.click(screen.getByRole("button", { name: "Удалить: Блок 3: Список" }));
    expect(last.map((b) => b.kind)).toEqual(["paragraph", "table"]);
    // первый блок нельзя поднять выше
    expect(screen.getByRole("button", { name: "Выше: Блок 1: Абзац" })).toBeDisabled();
  });
});
