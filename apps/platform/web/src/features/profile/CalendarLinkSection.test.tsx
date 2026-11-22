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

describe("Профиль · ссылка для календаря", () => {
  it("выдаёт ссылку один раз, потом показывает только дату выдачи и даёт сменить", async () => {
    signInAs("manager@demo.example");
    renderApp("/me?part=notifications");

    const block = await screen.findByTestId("profile-calendar-link");
    expect(within(block).getByText("Ссылки пока нет.")).toBeVisible();
    const get = await within(block).findByRole("button", { name: "Получить ссылку" });
    await waitFor(() => {
      expect(get).toBeEnabled();
    });
    fireEvent.click(get);

    const field = await within(block).findByLabelText<HTMLInputElement>("Ссылка для календаря");
    const first = field.value;
    expect(first).toMatch(/\/api\/v1\/calendar\/.+\.ics$/);
    expect(
      within(block).getByText("Сроки обновляются, когда вы заходите в Платформу."),
    ).toBeVisible();

    fireEvent.click(within(block).getByRole("button", { name: /Сменить ссылку/ }));
    const confirm = (await screen.findAllByRole("button", { name: /Сменить ссылку/ })).at(-1);
    expect(confirm).toBeDefined();
    fireEvent.click(confirm as HTMLElement);
    await waitFor(() => {
      const next = within(block).getByLabelText<HTMLInputElement>("Ссылка для календаря").value;
      expect(next).not.toBe(first);
    });
  });
});
