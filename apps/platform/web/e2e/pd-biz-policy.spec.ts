import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// PD-BIZ на MSW: «Защита данных для ИИ» в Настройках · Расходы на ИИ (политика «Деловая» / «Строгая», переключатель сканов
// с подписью «Паспорта и личные документы не загружайте») и подпись у поля загрузки в «Зарегистрировать входящее».
// axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/pd-biz/).
const WIDTHS = [1440, 390] as const;

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe("PD-BIZ · политика защиты данных для ИИ", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("админ выбирает политику; у поля загрузки — подпись", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/ai-spend");
    const region = page.getByRole("region", { name: "Защита данных для ИИ" });
    await expect(region).toBeVisible();
    await expect(region.getByRole("radio", { name: /Деловая/ })).toBeChecked();
    await expect(page.getByRole("switch", { name: "Читать сканы и фото писем" })).toBeChecked();
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await region.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `policy-business ${String(width)}`);
      if (width === 390) await noHorizontalScroll(page);
      await settledScreenshot(page, "policy-business");
    }

    // «Строгая»: сохранить, сканы блокируются с пояснением.
    await page.setViewportSize({ width: 1440, height: 900 });
    await region.getByRole("radio", { name: /Строгая/ }).check();
    await region.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Политика сохранена: «Строгая»")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Читать сканы и фото писем" })).toBeDisabled();
    await expect(
      page.getByText("При «Строгой» политике сканы и фото в модель не отправляются."),
    ).toBeVisible();
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await region.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `policy-strict ${String(width)}`);
      if (width === 390) await noHorizontalScroll(page);
      await settledScreenshot(page, "policy-strict");
    }

    // Вернуть «Деловую» (состояние моков живёт в localStorage браузера этого теста).
    await page.setViewportSize({ width: 1440, height: 900 });
    await region.getByRole("radio", { name: /Деловая/ }).check();
    await region.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Политика сохранена: «Деловая (рекомендуется)»")).toBeVisible();
    await signOut(page);

    // Делопроизводитель: у поля загрузки — «Паспорта и личные документы не загружайте».
    await loginAndWait(page, "registrar@demo.example");
    await spaGoto(page, "/eds/register");
    await expect(
      page.getByRole("heading", { level: 1, name: "Зарегистрировать входящее" }),
    ).toBeVisible();
    const hint = page.getByText(/Паспорта и личные документы не загружайте/);
    await expect(hint).toBeVisible();
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await hint.scrollIntoViewIfNeeded();
      await expectNoViolations(page, `register-upload ${String(width)}`);
      if (width === 390) await noHorizontalScroll(page);
      await settledScreenshot(page, "register-upload-hint");
    }
  });
});
