import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

vi.mock("@ant-design/charts", () => ({ Column: () => <div data-testid="chart" /> }));

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Главная · Сводка", () => {
  it("сроки на графике, просроченное списком, блоки без данных подписаны", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              role_id: "1",
              kind: "approve_quote",
              title: "Подписать КП",
              subtitle: "КП-1",
              due_label: "overdue",
              object: { kind: "quote", number: "КП-1", path: "/eds/drafts" },
            },
            {
              id: "2",
              role_id: "1",
              kind: "calc_task",
              title: "Расчёт",
              subtitle: "ЗВ-1",
              due_label: "today",
              object: { kind: "deal", number: "ЗВ-1", path: "/erp/calc" },
            },
          ],
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/summary");

    expect(await screen.findByRole("link", { name: "Подписать КП" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Расчёт" })).toBeNull();
    expect(
      screen.getByRole("img", { name: "Просрочено: 1, Сегодня: 1, Завтра: 0, Позже: 0" }),
    ).toBeVisible();
    expect(screen.getAllByText("Данные появятся здесь")).toHaveLength(3);
  });
});
