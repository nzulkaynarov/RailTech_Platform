import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../test/server";
import {
  buildMe,
  endSession,
  readSession,
  startSession,
  updateSession,
} from "../mocks/mockSession";
import { findUser } from "../mocks/fixtures/users";
import i18n from "../shared/i18n";
import { setViewportWidth } from "../test/viewport";
import { AppProviders } from "./providers";
import { routes } from "./router";
import { PANELS_STORAGE_KEY, usePanelsStore } from "./shell/panelsStore";

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, queryClient };
}

function signIn(
  email: string,
  activeRole?: "MANAGER" | "DIRECTOR" | "SUPPLY" | "ENGINEER" | "ACCOUNTANT" | "ADMIN",
) {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
  if (activeRole) updateSession({ activeRole });
}

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
  vi.restoreAllMocks();
});

describe("вход и страж маршрутов", () => {
  it("без сессии любой адрес ведёт на «Вход» с возвратом на тот же URL", async () => {
    const { router } = renderAt("/crm/leads?panel=open");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Вход в Платформу" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe("?next=%2Fcrm%2Fleads%3Fpanel%3Dopen");
  });

  it("при активной сессии «Вход» ведёт в очередь", async () => {
    signIn("manager@demo.example");
    const { router } = renderAt("/login");
    expect(await screen.findByRole("heading", { level: 1, name: "Моя очередь" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/dashboard/queue");
  });

  it("сессия закончилась во время работы: экран входа с возвратом и сообщением", async () => {
    signIn("manager@demo.example");
    const { router, queryClient } = renderAt("/crm/leads");
    await screen.findByRole("heading", { level: 1, name: "Все лиды" });
    endSession();
    await queryClient.invalidateQueries();
    await vi.waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    expect(router.state.location.search).toBe("?next=%2Fcrm%2Fleads&reason=expired");
    expect(await screen.findByText("Сессия истекла. Войдите снова.")).toBeVisible();
  });

  it("форма входа показывает текст ошибки по Error.code", async () => {
    renderAt("/login");
    fireEvent.change(await screen.findByLabelText("Электронная почта"), {
      target: { value: "disabled@demo.example" },
    });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Учётная запись отключена");
  });

  it("успешный вход ведёт в /dashboard/queue и открывает сессию", async () => {
    const { router } = renderAt("/login");
    fireEvent.change(await screen.findByLabelText("Электронная почта"), {
      target: { value: "director@demo.example" },
    });
    fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "anything" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Моя очередь" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/dashboard/queue");
    expect(readSession()?.userId).toBe("u-demo-director");
  });

  it("must_change_password: любой адрес ведёт на смену пароля", async () => {
    signIn("new@demo.example");
    const { router } = renderAt("/crm/leads");
    expect(await screen.findByRole("heading", { level: 1, name: "Смена пароля" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/change-password");
    expect(screen.queryByRole("navigation", { name: "Модули" })).not.toBeInTheDocument();
  });
});

describe("каркас на 1440", () => {
  it("неизвестный код модуля в Me.modules не роняет каркас: он пропускается", async () => {
    signIn("manager@demo.example");
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    if (!me) throw new Error("нет Me");
    server.use(
      http.get("*/me", () => HttpResponse.json({ ...me, modules: [...me.modules, "reports"] })),
    );
    renderAt("/dashboard/queue");
    expect(await screen.findByRole("heading", { level: 1, name: "Моя очередь" })).toBeVisible();
    const rail = screen.getByRole("navigation", { name: "Модули" });
    expect(within(rail).getAllByRole("link")).toHaveLength(6);
  });

  it("403 при выбранной активной роли: нейтральный текст и подсказка про «Все роли»", async () => {
    signIn("all@demo.example", "ACCOUNTANT");
    renderAt("/admin/roles");
    expect(await screen.findByText("Раздел недоступен для выбранной роли")).toBeVisible();
    expect(screen.getByText(/Выберите «Все роли» в меню профиля/)).toBeVisible();
  });

  it("рейл — модули роли, подменю — разделы активного модуля, главное действие неактивно", async () => {
    signIn("manager@demo.example");
    renderAt("/crm/leads");
    expect(await screen.findByRole("heading", { level: 1, name: "Все лиды" })).toBeVisible();

    const rail = screen.getByRole("navigation", { name: "Модули" });
    expect(
      within(rail)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["RT", "Dashboard", "CRM", "EDS", "ERP", "Chats"]);
    expect(within(rail).getByRole("link", { name: "CRM" })).toHaveAttribute("aria-current", "page");

    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    expect(within(menu).getByText("2. CRM")).toBeVisible();
    expect(
      within(menu)
        .getAllByRole("link")
        .map((a) => a.textContent.replace(/\d+, требует действия|\d+$/, "")),
    ).toEqual([
      "Все сообщения",
      "Все лиды",
      "Все клиенты",
      "Все заявки",
      "Каналы связи",
      "База знаний",
    ]);
    const action = within(menu).getByRole("button", { name: /Создать заявку/ });
    expect(action).toBeDisabled();
  });

  it("раздел вне роли — Forbidden, раздела нет в подменю, бокового окна нет", async () => {
    signIn("accountant@demo.example");
    renderAt("/crm/leads");
    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("complementary", { name: "Боковое окно" })).not.toBeInTheDocument();
    // у бухгалтера CRM виден только через «Все клиенты…» (чтение) — раздела «Все лиды» в подменю нет
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    expect(within(menu).queryByText("Все лиды")).not.toBeInTheDocument();
  });

  it("Admin по прямому URL для менеджера — Forbidden, а в рейле Admin нет", async () => {
    signIn("manager@demo.example");
    renderAt("/admin/roles");
    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("умолчание CRM · Все лиды — боковое окно скрыто; «Панель» открывает его и пишет ?panel=open", async () => {
    signIn("manager@demo.example");
    const { router } = renderAt("/crm/leads");
    await screen.findByRole("heading", { level: 1, name: "Все лиды" });
    expect(screen.queryByRole("complementary", { name: "Боковое окно" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Панель" }));
    expect(await screen.findByRole("complementary", { name: "Боковое окно" })).toBeVisible();
    expect(router.state.location.search).toContain("panel=open");
    expect(screen.getByRole("tab", { name: "Карточка" })).toBeVisible();
  });

  it("подменю сворачивается, состояние пишется в localStorage по пользователю и разделу", async () => {
    signIn("director@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    fireEvent.click(screen.getByRole("button", { name: "Свернуть меню" }));
    expect(screen.queryByRole("navigation", { name: "Разделы модуля" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Меню" })).toBeVisible();

    const stored = JSON.parse(window.localStorage.getItem(PANELS_STORAGE_KEY) ?? "{}") as Record<
      string,
      { menuOpen?: boolean }
    >;
    expect(stored["u-demo-director|/dashboard/queue"]?.menuOpen).toBe(false);
  });

  it("если localStorage бросает, панели всё равно работают", async () => {
    signIn("director@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    fireEvent.click(screen.getByRole("button", { name: "Свернуть меню" }));
    expect(screen.queryByRole("navigation", { name: "Разделы модуля" })).not.toBeInTheDocument();
  });

  it("смена активной роли в меню аватара пересчитывает рейл", async () => {
    signIn("all@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    const rail = () => screen.getByRole("navigation", { name: "Модули" });
    expect(within(rail()).getAllByRole("link")).toHaveLength(7);

    fireEvent.click(screen.getByRole("button", { name: /профиль и настройки/i }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Администратор" }));
    await vi.waitFor(() => {
      expect(
        within(rail())
          .getAllByRole("link")
          .map((a) => a.textContent),
      ).toEqual(["RT", "Dashboard", "EDS", "Chats", "Admin"]);
    });
  });

  it("Ctrl+K фокусирует поиск, но не перехватывает ввод в других полях", async () => {
    signIn("director@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    const search = screen.getByRole("searchbox", { name: "Глобальный поиск" });

    fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    expect(search).toHaveFocus();

    const field = document.createElement("textarea");
    document.body.append(field);
    field.focus();
    const event = new KeyboardEvent("keydown", {
      key: "k",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    field.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(field).toHaveFocus();
    field.remove();
  });

  it("неизвестный адрес — «Страница не найдена» внутри каркаса", async () => {
    signIn("manager@demo.example");
    renderAt("/crm/nothing");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Страница не найдена" }),
    ).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Модули" })).toBeVisible();
  });
});

describe("узкие экраны", () => {
  it("390: нижняя панель модулей, подменю и боковое окно — Drawer", async () => {
    setViewportWidth(390);
    signIn("director@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    expect(screen.getAllByRole("navigation", { name: "Модули" })).toHaveLength(1);
    expect(screen.queryByRole("navigation", { name: "Разделы модуля" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Меню" }));
    expect(await screen.findByRole("navigation", { name: "Разделы модуля" })).toBeVisible();
  });

  it("1100: боковое окно — Drawer, закрыт по умолчанию", async () => {
    setViewportWidth(1100);
    signIn("director@demo.example");
    renderAt("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
    expect(screen.queryByRole("tab", { name: "Сегодня" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Модули" })).toBeVisible();
  });
});
