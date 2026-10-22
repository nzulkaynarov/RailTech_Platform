import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../../app/providers";
import { routes } from "../../../app/router";
import { usePanelsStore } from "../../../app/shell/panelsStore";
import { readEmployees } from "../../../mocks/fixtures/employees";
import { findUser } from "../../../mocks/fixtures/users";
import { buildMe, endSession, readSession, startSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

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

function signIn(email: string) {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
}

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

/** Боковое окно появляется после загрузки профиля и маршрута — ждём его, а не берём сразу. */
async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

describe("Admin · Оргструктура (экран целиком на MSW)", () => {
  it("админ видит всех сотрудников; пока никто не выбран, в боковом окне — подсказка", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");

    expect(await screen.findByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" }),
    ).toBeVisible();
    expect(screen.getByText("Сотрудников: 10")).toBeVisible();
    const row = screen.getByRole("row", { name: /Демо Новичков/ });
    expect(within(row).getByText("Приглашён")).toBeVisible();
    expect(
      within(screen.getByRole("row", { name: /Демо Отключённый/ })).getByText("Отключён"),
    ).toBeVisible();
    expect(await within(await panelEl()).findByText("Объект не выбран")).toBeVisible();
  });

  it("карточка открывается из адреса и по клику на имя", async () => {
    signIn("admin@demo.example");
    const { router } = renderAt("/admin/org");

    fireEvent.click(await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" }));

    expect(
      await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" }),
    ).toBeVisible();
    expect(router.state.location.search).toContain("employee=u-demo-manager");
    expect(router.state.location.search).toContain("panel=open");
    expect(within(await panelEl()).getByRole("checkbox", { name: /^Менеджер/ })).toBeChecked();
  });

  it("выдача роли: список и сохранённые роли меняются, при следующем входе — модули по матрице", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-manager&panel=open");
    await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" });

    fireEvent.click(within(await panelEl()).getByRole("checkbox", { name: /^Менеджер/ }));
    fireEvent.click(within(await panelEl()).getByRole("checkbox", { name: /^Директор/ }));
    fireEvent.click(within(await panelEl()).getByRole("button", { name: "Сохранить роли" }));

    await waitFor(() => {
      expect(
        within(screen.getByRole("row", { name: /Демо Менеджеров/ })).getByText("Директор"),
      ).toBeVisible();
    });
    expect(readEmployees().find((e) => e.id === "u-demo-manager")?.roles).toEqual(["DIRECTOR"]);
    // тот же сотрудник входит позже: профиль мока считается по выданным ролям и матрице
    endSession();
    signIn("manager@demo.example");
    const me = buildMe(
      readSession() ?? { userId: "", activeRole: null, language: "ru", mustChangePassword: false },
    );
    expect(me?.roles).toEqual(["DIRECTOR"]);
    expect(me?.resources["erp.calc"]).toBe("full");
    expect(me?.modules).toContain("admin");
  });

  it("директор читает, но не меняет: ни приглашения, ни флажков", async () => {
    signIn("director@demo.example");
    renderAt("/admin/org?employee=u-demo-manager&panel=open");

    await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" });
    expect(screen.queryByRole("button", { name: "Пригласить сотрудника" })).toBeNull();
    expect(
      within(await panelEl()).getByText("Только просмотр: роли и доступ меняет администратор."),
    ).toBeVisible();
    expect(within(await panelEl()).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(await panelEl()).queryByRole("button", { name: "Сохранить роли" })).toBeNull();
  });

  it("сотрудник без раздела Admin видит «Нет доступа»", async () => {
    signIn("supply@demo.example");
    renderAt("/admin/org");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Открыть карточку/ })).toBeNull();
  });

  it("поиск и фильтр по статусу; ничего не найдено — слова и «Сбросить фильтры»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");
    await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" });

    const search = screen.getByRole("combobox", { name: "Статус" });
    fireEvent.mouseDown(search);
    fireEvent.click(await screen.findByTitle("Приглашён"));
    await waitFor(() => {
      expect(screen.getByText("Сотрудников: 2")).toBeVisible();
    });

    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по сотрудникам" }), {
      target: { value: "zzz" },
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "Никого не найдено" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    expect(await screen.findByText("Сотрудников: 10")).toBeVisible();
  });

  it("неизвестный сотрудник в адресе — «Сотрудник не найден» в боковом окне", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-missing&panel=open");

    expect(await within(await panelEl()).findByText("Сотрудник не найден")).toBeVisible();
  });

  it("список не загрузился — слова и «Повторить»", async () => {
    signIn("admin@demo.example");
    server.use(
      http.get("*/admin/users", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    renderAt("/admin/org");

    expect(
      await screen.findByRole("heading", { level: 2, name: "Не удалось загрузить сотрудников" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("форма приглашения открывается по ?invite=open у админа и не открывается у директора", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?invite=open&panel=open");
    expect(
      await within(await panelEl()).findByRole("heading", {
        level: 3,
        name: "Пригласить сотрудника",
      }),
    ).toBeVisible();
    endSession();
  });

  it("директору ?invite=open ничего не открывает", async () => {
    signIn("director@demo.example");
    renderAt("/admin/org?invite=open&panel=open");

    await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" });
    expect(
      within(await panelEl()).queryByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
    ).toBeNull();
  });
});
