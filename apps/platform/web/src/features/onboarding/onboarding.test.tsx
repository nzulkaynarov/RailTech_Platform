import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import * as navigate from "../../shared/lib/navigate";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  endSession();
});

/** Профиль уже запрошен и разобран: «строки нет» проверяем после ответа, а не пока он грузится. */
async function profileAnswered(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 150));
}

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

  it("карточка «Добро пожаловать»: имя и что делать утром — по разделам, не по кодам ролей", async () => {
    firstLogin("accountant@demo.example");
    const dialog = await screen.findByRole("dialog", { name: /Добро пожаловать, Демо/ });
    expect(within(dialog).queryByText(/Ваша роль/)).toBeNull(); // названий ролей в приветствии нет
    expect(within(dialog).getByText("Вот что вы будете делать утром:")).toBeInTheDocument();
    expect(within(dialog).getByText(/Подтвердите оплату по выписке/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Пропустить" })).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Больше не показывать" }),
    ).toBeInTheDocument();
  });

  it("«Подключить уведомления на телефон» — отдельная строка под списком, не его пункт; нужна, пока Telegram не привязан", async () => {
    firstLogin("supply@demo.example"); // Telegram не привязан
    const dialog = await screen.findByRole("dialog", { name: /Добро пожаловать/ });
    const button = await within(dialog).findByRole("button", {
      name: "Подключить уведомления на телефон",
    });
    for (const item of within(dialog).getAllByRole("listitem")) {
      expect(item).not.toContainElement(button);
    }
  });

  it("с привязанным Telegram строки нет", async () => {
    firstLogin("manager@demo.example"); // Telegram привязан
    const dialog = await screen.findByRole("dialog", { name: /Добро пожаловать/ });
    await waitFor(() => {
      expect(within(dialog).getAllByRole("listitem").length).toBeGreaterThan(0);
    });
    await profileAnswered();
    expect(
      within(dialog).queryByRole("button", { name: "Подключить уведомления на телефон" }),
    ).toBeNull();
  });

  it("тур из четырёх шагов: фокус на карточке, aria, Escape закрывает", async () => {
    firstLogin();
    fireEvent.click(await screen.findByRole("button", { name: "Показать, где что" }));
    const tour = await screen.findByRole("dialog", { name: "Знакомство с Платформой" });
    await waitFor(() => {
      expect(document.activeElement).toBe(tour);
    });
    expect(tour).not.toHaveAttribute("aria-modal"); // немодальный: страница под карточкой остаётся доступной
    expect(tour).toHaveAccessibleDescription(/Модули/);
    expect(within(tour).getByText("Шаг 1 из 4")).toBeInTheDocument();

    for (const title of ["«Задачи»", "Колокольчик", "Помощь"]) {
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

describe("«Подключить уведомления на телефон»: открытие бота", () => {
  const NAME = "Подключить уведомления на телефон";

  it("вкладка открыта до ответа, потом ведёт в бота; у вкладки нет opener", async () => {
    const tab = { location: { href: "" }, close: vi.fn(), opener: window };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    firstLogin("supply@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: NAME }));
    await waitFor(() => {
      expect(tab.location.href).toContain("https://t.me/");
    });
    expect(tab.opener).toBeNull();
  });

  it("браузер не дал открыть вкладку (window.open → null): переход в этой же вкладке", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    const go = vi.spyOn(navigate, "navigateTo").mockImplementation(() => undefined);
    firstLogin("supply@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: NAME }));
    await waitFor(() => {
      expect(go).toHaveBeenCalledWith(expect.stringContaining("https://t.me/"));
    });
  });

  it("сервер отказал: вкладка закрыта, ошибка видна словами", async () => {
    const tab = { location: { href: "" }, close: vi.fn(), opener: window };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    server.use(
      http.post("*/me/telegram-link", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "Бот не запущен.", details: { reason: "bot_not_running" } },
          { status: 409 },
        ),
      ),
    );
    firstLogin("supply@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: NAME }));
    await waitFor(() => {
      expect(tab.close).toHaveBeenCalled();
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/\S/);
    expect(tab.location.href).toBe("");
  });
});
