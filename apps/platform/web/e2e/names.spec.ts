import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  railLinks,
  settledScreenshot,
  waitForMotionEnd,
} from "./support/app";

// Названия модулей и разделов (волна 15 H5, UX-оценка 2026-10-27 §6): рейл, заголовок подменю без номера, крошки и
// заголовок вкладки — переводимые имена; внутренние коды (crm, eds, erp) — только в адресе. Снимки — `E2E_SCREENSHOT_DIR`.
const SYSTEM_NAMES = /\b(Dashboard|CRM|EDS|ERP|Chats|Admin|RBAC)\b/;

const RU = [
  {
    code: "dashboard",
    name: "Главная",
    title: "Главная",
    path: /\/dashboard\/queue$/,
    first: "Мои задачи",
  },
  {
    code: "crm",
    name: "Клиенты",
    title: "Клиенты и лиды",
    path: /\/crm\/messages$/,
    first: "Ждут ответа",
  },
  {
    code: "eds",
    name: "Документы",
    title: "Документы и согласования",
    path: /\/eds\/documents$/,
    first: "Все документы",
  },
  {
    code: "erp",
    name: "Расчёт",
    title: "Расчёт и склад",
    path: /\/erp\/requests$/,
    first: "Заявки в расчёте",
  },
  { code: "chats", name: "Чаты", title: "Чаты", path: /\/chats$/, first: "Все чаты" },
  {
    code: "admin",
    name: "Настройки",
    title: "Настройки компании",
    path: /\/admin\/roles$/,
    first: "Роли и права",
  },
] as const;

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

async function switchLanguage(page: Page, item: string): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: item }).click();
}

test.describe("названия модулей: десктоп", () => {
  test.skip(({ isMobile }) => isMobile, "ширину задаёт сценарий");

  test("директор, ru: рейл, заголовок подменю, крошки и вкладка браузера — без номеров и кодов систем; axe 0", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await expect(railLinks(page)).toHaveText(RU.map((m) => m.name));

    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    const crumbs = page.getByRole("navigation", { name: "Хлебные крошки" });
    for (const module of RU) {
      await railLinks(page).filter({ hasText: module.name }).click();
      await expect(page).toHaveURL(module.path);
      await expect(page.getByRole("heading", { level: 1, name: module.first })).toBeVisible();
      // Заголовок подменю — первая строка подменю: полное имя, без «N.»
      await expect(menu).toContainText(module.title);
      await expect(menu).not.toContainText(/\d\.\s/);
      await expect(menu).not.toContainText(SYSTEM_NAMES);
      await expect(crumbs).toContainText(module.name);
      await expect(crumbs).not.toContainText(SYSTEM_NAMES);
      expect(await page.title()).not.toMatch(SYSTEM_NAMES);
      await expectNoViolations(page, module.name);
      await settledScreenshot(page, `menu-${module.code}-ru`);
    }

    await page.goto("/admin/roles");
    const matrix = page.getByRole("table");
    await expect(
      matrix.getByRole("rowheader", { name: "Ждут ответа, Лиды, Каналы связи, База знаний бота" }),
    ).toBeVisible();
    await expect(matrix).toContainText("Клиенты и лиды");
    await expect(matrix).not.toContainText(SYSTEM_NAMES);
    await expectNoViolations(page, "роли и права");
    await settledScreenshot(page, "roles-matrix-ru");
  });

  test("директор, uz: рейл и подменю на узбекском, матрица прав с новыми подписями", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await switchLanguage(page, "O‘zbekcha");
    await expect(page.getByRole("heading", { level: 1, name: "Mening vazifalarim" })).toBeVisible();
    const rail = page.getByRole("navigation", { name: "Modullar" }).getByRole("link");
    await expect(rail.filter({ hasNotText: /^RT$/ })).toHaveText([
      "Asosiy",
      "Mijozlar",
      "Hujjatlar",
      "Hisob",
      "Chatlar",
      "Sozlamalar",
    ]);

    await rail.filter({ hasText: "Mijozlar" }).click();
    const menu = page.getByRole("navigation", { name: "Modul bo‘limlari" });
    await expect(menu).toContainText("Mijozlar va lidlar");
    await expect(menu).toContainText("Javob kutmoqda");
    await expect(menu).not.toContainText(SYSTEM_NAMES);
    await settledScreenshot(page, "menu-crm-uz");

    await page.goto("/admin/roles");
    await expect(page.getByRole("table")).toContainText("Mijozlar va lidlar");
    await expect(page.getByRole("table")).not.toContainText(SYSTEM_NAMES);
    await expectNoViolations(page, "roli uz");
    await settledScreenshot(page, "roles-matrix-uz");
  });
});

test.describe("названия модулей: 390 @mobile", () => {
  test("нижняя панель и подменю в Drawer — переводимые имена (ru и uz)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    const bar = page.getByRole("navigation", { name: "Модули" });
    await expect(bar.getByRole("link")).toHaveText(RU.map((m) => m.name));
    await bar.getByRole("link", { name: "Клиенты" }).click();
    await page.getByRole("button", { name: "Меню" }).click();
    const drawerMenu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(drawerMenu).toContainText("Клиенты и лиды");
    await expect(drawerMenu).not.toContainText(/\d\.\s/);
    await expectNoViolations(page, "drawer ru");
    await settledScreenshot(page, "mobile-menu-ru");
    await page.keyboard.press("Escape");
    await expect(drawerMenu).toBeHidden();

    await switchLanguage(page, "O‘zbekcha");
    const barUz = page.getByRole("navigation", { name: "Modullar" });
    await expect(barUz.getByRole("link")).toHaveText([
      "Asosiy",
      "Mijozlar",
      "Hujjatlar",
      "Hisob",
      "Chatlar",
      "Sozlamalar",
    ]);
    await page.getByRole("button", { name: "Menyu" }).click();
    await expect(page.getByText("Mijozlar va lidlar")).toBeVisible();
    await settledScreenshot(page, "mobile-menu-uz");
  });
});
