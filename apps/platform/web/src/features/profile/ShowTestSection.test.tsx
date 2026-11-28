import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Профиль · «Показывать тестовые»", () => {
  it("по умолчанию выключено, любой сотрудник включает и выключает, настройка сохраняется", async () => {
    signInAs("manager@demo.example");
    renderApp("/me");

    const block = await screen.findByTestId("profile-show-test");
    const toggle = within(block).getByRole("switch", {
      name: "Показывать тестовые компании и их документы",
    });
    expect(toggle).not.toBeChecked();

    fireEvent.click(toggle);
    await waitFor(() => {
      expect(toggle).toBeChecked();
    });
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(toggle).not.toBeChecked();
    });
  });
});
