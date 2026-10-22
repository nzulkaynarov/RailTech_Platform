import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { Consequence } from "./Consequence";

describe("Consequence", () => {
  it("группа «Что произойдёт» с нумерованными строками", () => {
    renderUi(<Consequence items={["Первое", "Второе", "Третье"]} />);
    const group = screen.getByRole("group", { name: "Что произойдёт" });
    const items = within(group).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["1Первое", "2Второе", "3Третье"]);
    expect(group.querySelectorAll('[aria-hidden="true"]')).toHaveLength(3);
  });

  it("свой заголовок и язык", () => {
    renderUi(<Consequence title="После нажатия" items={["Раз"]} />);
    expect(screen.getByRole("group", { name: "После нажатия" })).toBeVisible();
  });

  it("заголовок по языку интерфейса", () => {
    renderUi(<Consequence items={["One"]} />, { language: "uz" });
    expect(screen.getByRole("group", { name: "Nima bo‘ladi" })).toBeVisible();
  });
});
