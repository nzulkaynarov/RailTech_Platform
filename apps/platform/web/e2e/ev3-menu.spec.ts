import { expect, test, type Page } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕВ-3а и ЕВ-3б: «Почта» стоит в меню «Документов» сразу за «Входящими», «Шаблонов» в этом меню нет (вход — ссылкой на
// экране и из Настроек), «Чатов» в меню Органайзера нет, пустых блоков «Сводки» нет; старые адреса ведут на новые.
// Снимки 1440 и 390 с axe.
const WIDTHS = [1440, 390] as const;
const size = (width: number) => ({ width, height: width === 390 ? 844 : 900 });

/** Подменю модуля: на телефоне оно в шторке по кнопке «Меню». */
async function openMenu(page: Page, width: number) {
  if (width === 390) await page.getByRole("button", { name: "Меню", exact: true }).click();
  const menu = page.getByRole("navigation", { name: "Разделы модуля" });
  await expect(menu).toBeVisible();
  return menu;
}

const labels = async (menu: ReturnType<Page["getByRole"]>) =>
  (await menu.getByRole("link").allTextContents())
    .map((text) => text.replace(/\d+, требует действия|\d+$/, "").trim())
    .filter(Boolean); // ссылка-шестерёнка «Настройки модуля» без подписи в тексте

test.describe("ЕВ-3: меню модулей", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`Документы: «Почта» за «Входящими», «Шаблонов» в меню нет, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/mail");
      await expect(page.getByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
      const menu = await openMenu(page, width);
      expect(await labels(menu)).toEqual(["Входящие", "Почта", "Исходящие", "Внутренние", "Архив"]);
      await expect(menu.getByRole("link", { name: /^Почта/ })).toHaveAttribute(
        "aria-current",
        "page",
      );
      await expectNoViolations(page, `documents menu ${String(width)}`);
      await settledScreenshot(page, "documents-menu");
    });

    test(`Документы: ссылка «Шаблоны документов» на экране ведёт в Настройки, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/documents?box=outgoing");
      await expect(page.getByRole("heading", { level: 1, name: "Исходящие" })).toBeVisible();
      const link = page.getByRole("link", { name: "Шаблоны документов" });
      await expect(link).toBeVisible();
      await expectNoViolations(page, `documents templates link ${String(width)}`);
      await settledScreenshot(page, "documents-templates-link");
      await link.click();
      await expect(page).toHaveURL(/\/admin\/templates/);
      await expect(
        page.getByRole("heading", { level: 1, name: "Шаблоны документов" }),
      ).toBeVisible();
    });

    test(`Органайзер без «Чатов», ${String(width)}`, async ({ page }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/chats/contacts");
      await expect(page.getByRole("heading", { level: 1, name: "Люди" })).toBeVisible();
      expect(await labels(await openMenu(page, width))).toEqual(["Календарь", "Люди"]);
      await settledScreenshot(page, "organizer-menu");
    });

    test(`Контакты без «Почты», ${String(width)}`, async ({ page }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/crm/leads");
      await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
      expect(await labels(await openMenu(page, width))).toEqual([
        "Лиды",
        "Контрагенты",
        "База знаний",
      ]);
      await settledScreenshot(page, "contacts-menu");
    });

    test(`Сводка без пустых блоков, ${String(width)}`, async ({ page }) => {
      await page.setViewportSize(size(width));
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/dashboard/summary");
      await expect(page.getByRole("heading", { level: 1, name: "Сводка" })).toBeVisible();
      await expect(page.getByText("Данные появятся здесь")).toHaveCount(0);
      await expect(page.getByText("Прибыль по проектам")).toHaveCount(0);
      await expectNoViolations(page, `summary ${String(width)}`);
      await settledScreenshot(page, "summary");
    });
  }

  test("старые адреса разделов ведут на новые (таблица с датой удаления)", async ({ page }) => {
    await loginAndWait(page, "all@demo.example");
    for (const [from, to] of [
      ["/dashboard/projects", /\/eds\/projects$/],
      ["/crm/channels", /\/admin\/telegram$/],
      ["/crm/messages?lead=L-2041", /\/crm\/leads\?scope=waiting&lead=L-2041$/],
      ["/eds/outbox", /\/eds\/documents\?box=outgoing$/],
      ["/chats?scope=external", /\/crm\/leads\?scope=waiting$/],
    ] as const) {
      await page.goto(from);
      await expect(page, from).toHaveURL(to);
    }
  });
});
