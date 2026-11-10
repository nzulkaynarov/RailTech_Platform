import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Органайзер · Чаты", () => {
  it("показывает раскладку: группы и поле сообщения; выдуманных данных нет", async () => {
    signInAs("director@demo.example");
    renderApp("/chats");
    expect(await screen.findByRole("heading", { level: 1, name: "Чаты" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "Обсуждения на объектах" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "Личные" })).toBeVisible();
    expect(screen.getAllByText("Данные появятся здесь")).toHaveLength(3);
  });
});
