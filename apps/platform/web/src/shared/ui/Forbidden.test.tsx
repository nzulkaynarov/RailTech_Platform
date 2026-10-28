import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { Forbidden } from "./Forbidden";

describe("Forbidden", () => {
  it("заголовок страницы, пояснение и рабочая кнопка «Написать администратору» (W15-H7)", () => {
    renderUi(<Forbidden />);
    expect(screen.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 2, name: "Этот раздел недоступен для вашей роли" }),
    ).toBeVisible();
    const button = screen.getByRole("button", { name: /Написать администратору/ });
    expect(button).toBeEnabled();
    expect(document.title).toBe("Нет доступа — RailTech Platform");
  });

  it("«Раздел доступен ролям: …»", () => {
    renderUi(<Forbidden roles={["Директор", "Бухгалтер"]} />);
    expect(screen.getByText(/Раздел доступен ролям: Директор, Бухгалтер\./)).toBeVisible();
  });

  it("активная роль — подсказка «Все роли»", () => {
    renderUi(<Forbidden activeRole />);
    expect(screen.getByText("Раздел недоступен для выбранной роли")).toBeVisible();
    expect(screen.getByText(/Выберите «Все роли»/)).toBeVisible();
  });

  it("встроенный: без h1 и без смены заголовка вкладки", () => {
    document.title = "Витрина";
    renderUi(<Forbidden embedded />);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("heading", { level: 3 })).toBeVisible();
    expect(document.title).toBe("Витрина");
  });
});
