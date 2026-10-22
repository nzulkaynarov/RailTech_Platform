import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export const DEMO_PASSWORD = "demo-pass-1";

/** Вход через экран «Вход» (MSW принимает любой непустой пароль кроме `wrong-password`). */
export async function login(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
}

export async function loginAndWait(page: Page, email: string): Promise<void> {
  await login(page, email);
  await expect(page).toHaveURL(/\/dashboard\/queue$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

export function railLinks(page: Page) {
  return page
    .getByRole("navigation", { name: "Модули" })
    .getByRole("link")
    .filter({ hasNotText: /^RT$/ });
}

export async function openAvatarMenu(page: Page): Promise<void> {
  await page
    .getByRole("button", { name: /профиль и настройки|profil va sozlamalar|profile and settings/i })
    .click();
}

export async function screenshot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png` });
}

/** Скриншот после того, как закончились переходы antd (200–300 мс), чтобы кадр не ловил анимацию. */
export async function settledScreenshot(page: Page, name: string): Promise<void> {
  if (!process.env["E2E_SCREENSHOT_DIR"]) return;
  await page.waitForTimeout(500);
  await screenshot(page, name);
}

/**
 * Переход внутри SPA без перезагрузки страницы: `pushState` + `popstate` (react-router слушает его). Полная загрузка dev-сервера
 * vite с нераспакованным antd — секунды на медленном раннере CI; циклы по десяткам адресов ходят этим способом.
 */
export async function spaGoto(page: Page, path: string): Promise<void> {
  await page.evaluate(
    `(() => { window.history.pushState({}, "", ${JSON.stringify(path)}); window.dispatchEvent(new PopStateEvent("popstate")); })()`,
  );
}

/**
 * Ждёт конца анимаций antd (появление, исчезновение): во время fade-in/out `opacity` меняет вычисленный цвет, и axe
 * ловит «нарушение контраста» у закрывающегося выпадающего меню под модальным окном (на медленном Linux-раннере — стабильно).
 */
export async function waitForMotionEnd(page: Page): Promise<void> {
  await page.waitForFunction(
    `() => !document.querySelector('[class*="-appear"], [class*="-enter"], [class*="-leave"]')`,
  );
}
