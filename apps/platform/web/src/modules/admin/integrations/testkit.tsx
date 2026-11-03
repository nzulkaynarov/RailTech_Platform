import { render, screen, waitFor } from "@testing-library/react";
import { createQueryClient } from "../../../app/queryClient";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, expect } from "vitest";

import { AppProviders } from "../../../app/providers";
import { routes } from "../../../app/router";
import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetIntegrations } from "../../../mocks/fixtures/integrations";
import { findUser } from "../../../mocks/fixtures/users";
import { endSession, startSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { setViewportWidth } from "../../../test/viewport";

/** Общая оснастка тестов экрана «Внешние интеграции»: вход, рендер по адресу, боковое окно, учёт пропущенных ключей i18n. */
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

/** Карточки «Подключений» со своей страницей Настроек (SET-IA): адрес и заголовок страницы. */
const OWN_PAGE: Partial<Record<string, readonly [string, string]>> = {
  telegram: ["/admin/telegram", "Telegram"],
  mail: ["/admin/mail", "Почта"],
  spend: ["/admin/ai-spend", "Расходы на ИИ"],
};

/**
 * Содержимое карточки: у Telegram, Почты и Расходов — своя страница (основное окно), у остальных — боковое окно
 * «Подключений» (`?card=`). Вход — до вызова (`signIn`).
 */
export async function openCard(card: string): Promise<HTMLElement> {
  const own = OWN_PAGE[card];
  if (!own) {
    renderAt(`/admin/integrations?card=${card}&panel=open`);
    return panelEl();
  }
  renderAt(own[0]);
  await screen.findByRole("heading", { level: 1, name: own[1] });
  const main = document.getElementById("main-content");
  if (!main) throw new Error("нет основного окна");
  return main;
}

const missing: string[] = [];

/** Подготовка и уборка теста: чистое состояние моков, ширина 1440, русский язык, ни одного пропущенного ключа словаря. */
export function setupIntegrationsTests(width = 1440): void {
  beforeEach(() => {
    window.localStorage.clear();
    resetIntegrations();
    usePanelsStore.setState({ entries: {} });
    setViewportWidth(width);
    missing.length = 0;
    i18n.options.saveMissing = true;
    // Ключ с пустым запасным значением (`defaultValue: ""`) — осознанно необязательный (подсказка поля формы бота на
    // странице «Расходы на ИИ», SET-IA), как в оснастке настроек бота.
    i18n.options.missingKeyHandler = (_languages, namespace, key, fallback) => {
      if (fallback !== "") missing.push(`${namespace}:${key}`);
    };
    void i18n.changeLanguage("ru");
  });
  afterEach(() => {
    endSession();
    i18n.options.saveMissing = false;
    expect(missing, "в словаре нет ключей, которые просит экран").toEqual([]);
  });
}
