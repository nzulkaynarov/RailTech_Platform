import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
});

function firstLogin(email = "manager@demo.example") {
  window.localStorage.setItem("rt-pf-mock-onboarding", "pending");
  signInAs(email);
  renderApp("/dashboard/queue");
}

describe("Первый вход", () => {
  it("сотрудник, уже работающий в Платформе, приветствия не видит", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    await screen.findByRole("button", { name: "Помощь (клавиша ?)" });
    expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
  });

  it("карточка «Добро пожаловать»: имя, роль и что делать утром — по разделам, не по кодам ролей", async () => {
    firstLogin("accountant@demo.example");
    const dialog = await screen.findByRole("dialog", { name: /Добро пожаловать, Демо/ });
    expect(within(dialog).getByText("Ваша роль — Бухгалтер.")).toBeInTheDocument();
    expect(within(dialog).getByText("Вот что вы будете делать утром:")).toBeInTheDocument();
    expect(within(dialog).getByText(/Подтвердите оплату по выписке/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Пропустить" })).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Больше не показывать" }),
    ).toBeInTheDocument();
  });

  it("тур из четырёх шагов: фокус на карточке, aria, Escape закрывает", async () => {
    firstLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Показать, где что" }));
    const tour = await screen.findByRole("dialog", { name: "Знакомство с Платформой" });
    await waitFor(() => {
      expect(document.activeElement).toBe(tour);
    });
    expect(tour).toHaveAttribute("aria-modal", "true");
    expect(tour).toHaveAccessibleDescription(/Модули/);
    expect(within(tour).getByText("Шаг 1 из 4")).toBeInTheDocument();

    for (const title of ["«Мои задачи»", "Колокольчик", "Помощь"]) {
      fireEvent.click(within(tour).getByRole("button", { name: /^(Дальше)$/ }));
      expect(await within(tour).findByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(within(tour).getByText("Шаг 4 из 4")).toBeInTheDocument();
    expect(within(tour).queryByRole("button", { name: "Дальше" })).toBeNull();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Знакомство с Платформой" })).toBeNull();
    });
  });

  it("«Пропустить» прячет приветствие до конца сеанса, но флаг в профиле не ставит", async () => {
    firstLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Пропустить" }));
    await waitFor(() => {
      expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
    });
    cleanup();
    renderApp("/dashboard/queue"); // тот же сеанс (sessionStorage), профиль всё ещё «первый вход»
    await screen.findByRole("button", { name: "Помощь (клавиша ?)" });
    expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
    cleanup();
    window.sessionStorage.clear(); // новый сеанс браузера — приветствие снова
    renderApp("/dashboard/queue");
    expect(await screen.findByRole("dialog", { name: /Добро пожаловать/ })).toBeInTheDocument();
  });

  it("«Больше не показывать» сохраняет флаг в профиле: новый сеанс приветствия не видит", async () => {
    firstLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Больше не показывать" }));
    await waitFor(() => {
      expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
    });
    cleanup();
    window.sessionStorage.clear();
    renderApp("/dashboard/queue");
    await screen.findByRole("button", { name: "Помощь (клавиша ?)" });
    await waitFor(() => {
      expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
    });
  });

  it("«Готово» на последнем шаге тоже сохраняет флаг", async () => {
    firstLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Показать, где что" }));
    const tour = await screen.findByRole("dialog", { name: "Знакомство с Платформой" });
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(within(tour).getByRole("button", { name: "Дальше" }));
    }
    fireEvent.click(await within(tour).findByRole("button", { name: "Готово" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Знакомство с Платформой" })).toBeNull();
    });
    cleanup();
    window.sessionStorage.clear();
    renderApp("/dashboard/queue");
    await screen.findByRole("button", { name: "Помощь (клавиша ?)" });
    expect(screen.queryByText(/Добро пожаловать/)).toBeNull();
  });
});
