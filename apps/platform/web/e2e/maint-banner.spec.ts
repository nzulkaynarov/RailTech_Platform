import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { loginAndWait, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Плановое обновление (DECISIONS 2026-11-23): плашка над шапкой по /maintenance.json (на MSW — window.__rtMockMaintenance).
async function mockNotice(page: Page, startsInMin: number, extra: Record<string, unknown> = {}) {
  const startsAt = new Date(Date.now() + startsInMin * 60_000).toISOString();
  await page.addInitScript(
    `window.__rtMockMaintenance = ${JSON.stringify({ starts_at: startsAt, minutes: 3, kind: "planned", ...extra })};`,
  );
}

test("за 20 минут: плашка с временем, скрывается; axe чист; 390 без горизонтальной прокрутки @mobile", async ({
  page,
}) => {
  await mockNotice(page, 20);
  await loginAndWait(page, "director@demo.example");
  const banner = page.getByRole("status").filter({ hasText: "Обновление Платформы в" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(
    /в \d{2}:\d{2} — работа прервётся на 2–3 минуты\. Сохраните изменения\./,
  );
  await settledScreenshot(page, "maint-banner-soon");
  await expectNoViolations(page, "плашка планового обновления");
  const overflow = await page.evaluate(
    `document.documentElement.scrollWidth > document.documentElement.clientWidth`,
  );
  expect(overflow).toBe(false);

  await banner.getByRole("button", { name: "Скрыть" }).click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("срочное исправление — другое слово", async ({ page }) => {
  await mockNotice(page, 10, { kind: "urgent" });
  await loginAndWait(page, "director@demo.example");
  await expect(
    page.getByRole("status").filter({ hasText: "Срочное исправление Платформы в" }),
  ).toBeVisible();
});

test("время работ: «Идёт обновление», без кнопки скрытия; axe чист @mobile", async ({ page }) => {
  await mockNotice(page, -1);
  await loginAndWait(page, "director@demo.example");
  const banner = page.getByRole("status").filter({ hasText: "Идёт обновление" });
  await expect(banner).toContainText("через пару минут страница обновится сама.");
  await expect(banner.getByRole("button")).toHaveCount(0);
  await settledScreenshot(page, "maint-banner-running");
  await expectNoViolations(page, "плашка во время работ");
});

test("без файла плашки нет", async ({ page }) => {
  await loginAndWait(page, "director@demo.example");
  await expect(page.getByRole("status").filter({ hasText: /обновлени|исправлени/i })).toHaveCount(
    0,
  );
});
