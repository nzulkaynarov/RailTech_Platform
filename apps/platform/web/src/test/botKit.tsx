import { cleanup, render, waitFor } from "@testing-library/react";
import { createQueryClient } from "../app/queryClient";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, expect } from "vitest";

import { AppProviders } from "../app/providers";
import { routes } from "../app/router";
import { usePanelsStore } from "../app/shell/panelsStore";
import { resetKb } from "../mocks/fixtures/kb";
import { findUser } from "../mocks/fixtures/users";
import { endSession, startSession } from "../mocks/mockSession";
import i18n from "../shared/i18n";
import { setViewportWidth } from "./viewport";

/** Оснастка тестов «База знаний» и «Настройки бота»: вход, рендер по адресу, боковое окно, учёт пропущенных ключей i18n. */
export function renderAt(path: string) {
  const queryClient = createQueryClient({ retry: false, staleTime: 0 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, queryClient };
}

export function signIn(email: string): void {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
}

/** Боковое окно появляется после загрузки профиля и маршрута — ждём его. */
export async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

const missing: string[] = [];

/** Подготовка и уборка теста: чистое состояние моков, ширина 1440, русский язык, ни одного пропущенного ключа словаря. */
export function setupBotTests(width = 1440): void {
  beforeEach(() => {
    window.localStorage.clear();
    resetKb();
    usePanelsStore.setState({ entries: {} });
    setViewportWidth(width);
    missing.length = 0;
    i18n.options.saveMissing = true;
    // Ключ с пустым запасным значением (`defaultValue: ""`) — осознанно необязательный (подсказка, единица измерения).
    i18n.options.missingKeyHandler = (_languages, namespace, key, fallback) => {
      if (fallback !== "") missing.push(`${namespace}:${key}`);
    };
    void i18n.changeLanguage("ru");
  });
  afterEach(() => {
    cleanup();
    endSession();
    i18n.options.saveMissing = false;
    expect(missing, "в словаре нет ключей, которые просит экран").toEqual([]);
  });
}
