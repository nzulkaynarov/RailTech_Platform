import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("h1 20/600 с подзаголовком и действием", () => {
    renderUi(
      <PageHeader
        title="Задачи"
        subtitle="Директор · четверг"
        extra={<button type="button">Действие</button>}
      />,
    );
    const heading = screen.getByRole("heading", { level: 1, name: "Задачи" });
    expect(heading).toHaveStyle({ fontSize: "20px", fontWeight: "600", lineHeight: "28px" });
    expect(screen.getByText("Директор · четверг")).toBeVisible();
    expect(screen.getByRole("button", { name: "Действие" })).toBeVisible();
  });

  it("readOnly: одна плашка «Только просмотр» рядом с действием", () => {
    renderUi(<PageHeader title="Сотрудники" readOnly extra={<button type="button">Ещё</button>} />);
    expect(screen.getAllByText("Только просмотр")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Ещё" })).toBeVisible();
  });

  it("без readOnly плашки нет", () => {
    renderUi(<PageHeader title="Сотрудники" />);
    expect(screen.queryByText("Только просмотр")).toBeNull();
  });
});
