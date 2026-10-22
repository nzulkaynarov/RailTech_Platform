import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("статус, пояснение и одно действие", () => {
    renderUi(
      <EmptyState
        title="Заявок пока нет"
        text="Они приходят из CRM и кабинета — или создайте вручную."
        action={<button type="button">Создать заявку</button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Заявок пока нет" })).toBeVisible();
    expect(screen.getByText(/Они приходят из CRM/)).toBeVisible();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("без действия кнопок нет; уровень заголовка h3 для бокового окна", () => {
    renderUi(<EmptyState title="Пусто" text="Здесь будет список" level={3} compact />);
    expect(screen.getByRole("heading", { level: 3, name: "Пусто" })).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
