import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// НАСТ-П1 «Правда о состоянии» (аудит Настроек §6.2): слово состояния службы приходит из ответа и стоит одно и то же на
// «Состоянии», в «Сервисах» и в «Первом запуске»; «Работает» — только по свежей проверке. Снимки 1440 и 390 и axe для PR
// (`E2E_SCREENSHOT_DIR=docs/screens/nast-p1`).
const WIDTHS = [1440, 390] as const;
const KEY = "rt-pf-mock-integrations";

/** Мок-стенд: у связи с расчётами нет ни одной проверки — адрес и ключи есть, а «Работает» сказать нечем. */
async function seedUnverified(page: Page): Promise<void> {
  await page.evaluate(`(() => {
    const key = ${JSON.stringify(KEY)};
    const raw = window.localStorage.getItem(key);
    if (!raw) return;
    const state = JSON.parse(raw);
    for (const service of state.services) {
      if (service.key.startsWith("erp_")) service.checked_at = null;
    }
    state.erp.token_updated_at = null;
    window.localStorage.setItem(key, JSON.stringify(state));
  })()`);
  // обзор уже в кэше страницы: перечитываем целиком, чтобы мок отдал подправленное состояние
  await page.reload();
}

async function shot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0);
  await page.evaluate("document.getElementById('main-content')?.scrollTo(0, 0)");
  await settledScreenshot(page, name);
}

test.describe("НАСТ-П1: правда о состоянии", () => {
  test("«Состояние», «Сервисы» и «Первый запуск»: одно слово на одном факте, оба размера, axe 0", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    // Первое же действие записывает состояние мок-стенда в хранилище страницы: после него его можно подправить
    await spaGoto(page, "/admin/integrations");
    const first = page.locator('article[data-card="mail"]');
    await first.getByRole("button", { name: "Проверить: Почта" }).click();
    await expect(first.getByText("Проверено: Работает")).toBeVisible();
    await seedUnverified(page);

    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });

      await spaGoto(page, "/admin");
      const services = page.getByRole("region", { name: "Службы" });
      await expect(services).toBeVisible();
      await expect(services.locator('[data-service="mail"]')).toContainText("Работает");
      await expect(services.locator('[data-service="erp"]')).toContainText(
        "Настроено, не проверено",
      );
      await expect(page.getByText("Внешняя проверка доступности")).toHaveCount(0);
      await shot(page, `state`);
      await expectNoViolations(page, `Состояние, ${String(width)}`);

      await spaGoto(page, "/admin/integrations");
      const erp = page.locator('article[data-card="erp"]');
      await expect(erp).toContainText("Настроено, не проверено");
      await expect(erp).toContainText("связь с расчётами");
      await expect(page.locator('article[data-card="mail"]')).toContainText(
        "отправка и приём писем",
      );
      await shot(page, `services`);
      await expectNoViolations(page, `Сервисы, ${String(width)}`);

      await spaGoto(page, "/admin/setup");
      await expect(page.getByText("Настроено, не проверено").first()).toBeVisible();
      await expect(page.locator('li[data-step="mail"]')).not.toContainText("Готово");
      await shot(page, `setup`);
      await expectNoViolations(page, `Первый запуск, ${String(width)}`);
    }
  });

  test("«Проверить» на карточке «Почта» меняет слово: итог после ответа, не раньше", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/integrations");
    const mail = page.locator('article[data-card="mail"]');
    await expect(mail).toContainText("Внимание");

    await mail.getByRole("button", { name: "Проверить: Почта" }).click();

    await expect(mail.getByText("Проверено: Работает")).toBeVisible();
    await expect(mail.locator(".ant-tag").first()).toHaveText("Работает");
    await shot(page, "services-after-check");
  });
});
