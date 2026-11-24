import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕД-3, ЕД-5 на MSW: логотип компании и фото сотрудника в строках реестров (проекты, счета, письма, документы) — общие
// ячейки CompanyCell и PersonCell вместо текста; у компании без логотипа — буквы названия. Снимки 1440 и 390 с axe.
const AVATAR = `data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" fill="#b45f06"/><circle cx="48" cy="38" r="16" fill="#fff"/><rect x="20" y="60" width="56" height="30" rx="14" fill="#fff"/></svg>',
)}`;

/**
 * Справочник сотрудников со своими фото по id сотрудника в строках проектов (2 — менеджер, 7 — помощник). MSW живёт в
 * service worker, `page.route` его ответы не видит, поэтому подменяем fetch страницы.
 */
async function withStaffPhotos(page: Page): Promise<void> {
  const body = {
    items: ["1", "2", "7", "51"].map((id) => ({
      id,
      name: `Сотрудник ${id}`,
      position: null,
      avatar_url: AVATAR,
      active: true,
      roles: [],
    })),
  };
  await page.addInitScript(`(() => {
    const original = window.fetch.bind(window);
    const payload = ${JSON.stringify(JSON.stringify(body))};
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      return /\\/api\\/v1\\/staff(\\?|$)/.test(url)
        ? Promise.resolve(new Response(payload, { status: 200, headers: { "content-type": "application/json" } }))
        : original(input, init);
    };
  })();`);
}

const SCREENS = [
  {
    name: "projects",
    path: "/eds/projects",
    heading: /Проекты/,
    table: /Проекты: номер, клиент/,
    photos: true,
  },
  {
    name: "payments",
    path: "/eds/payments?tab=all",
    heading: /Финансы/,
    table: /Счета/,
    photos: false,
  },
  {
    name: "documents",
    path: "/eds/documents?scope=all",
    heading: /Все документы/,
    table: null,
    photos: false,
  },
] as const;

for (const width of [1440, 390] as const) {
  for (const screen of SCREENS) {
    test(
      `${screen.name}: логотип клиента и фото сотрудника в строках, ${String(width)}`,
      { tag: "@mobile" },
      async ({ page }) => {
        test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        if (screen.photos) await withStaffPhotos(page);
        await loginAndWait(page, "accountant@demo.example");
        await spaGoto(page, screen.path);
        await expect(page.getByRole("heading", { level: 1, name: screen.heading })).toBeVisible();
        if (screen.name !== "documents") {
          // логотип по адресу BFF с версией и буквы названия у компании без логотипа
          await expect(page.locator('main img[src*="/logo?v="]').first()).toBeVisible();
          await expect(
            page.locator('main .pf-entity__pic--square[data-photo="false"]').first(),
          ).toBeVisible();
        }
        if (screen.photos) {
          await expect(page.locator('main img[src^="data:image/svg"]').first()).toBeVisible();
        }
        await settledScreenshot(page, screen.name);
        await expectNoViolations(page, `${screen.name} ${String(width)}`);
      },
    );
  }

  test(
    `входящие письма: логотип корреспондента, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/inbox?status=all");
      await expect(page.locator('main img[src*="/logo?v="]').first()).toBeVisible();
      await settledScreenshot(page, "inbox");
      await expectNoViolations(page, `inbox ${String(width)}`);
    },
  );

  test(
    `лиды: ответственный — общая ячейка человека, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await withStaffPhotos(page);
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/crm/leads");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await settledScreenshot(page, "leads");
      await expectNoViolations(page, `leads ${String(width)}`);
    },
  );
}
