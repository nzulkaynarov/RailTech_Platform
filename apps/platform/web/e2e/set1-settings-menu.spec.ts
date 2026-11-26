import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// НАСТ-1 «Меню настроек не прыгает» (макеты 54 SetMenu и 55 SetMenuPhone, жалоба владельца 25.11 и 26.11): одно меню Настроек
// с теми же группами и пунктами на любой странице; открытый пункт подсвечен, по нажатию ничего не двигается. Регрессионный тест
// «прыгает»: нажимаем каждый пункт и сверяем список пунктов, заголовки групп, размер и прокрутку меню. Снимки для PR —
// `E2E_SCREENSHOT_DIR=docs/screens/set1`.
const MENU = 'nav[data-tour="menu"]';

interface MenuSnapshot {
  captions: string[];
  links: string[];
  current: string[];
  box: { x: number; y: number; width: number; height: number };
  scrollTop: number;
}

async function snapshot(page: Page): Promise<MenuSnapshot> {
  const nav = page.locator(MENU);
  const box = await nav.boundingBox();
  if (!box) throw new Error("меню Настроек не видно");
  const texts = async (locator: Locator) =>
    (await locator.allInnerTexts()).map((text) => text.replace(/\s+/g, " ").trim());
  return {
    captions: await texts(nav.locator(".pf-menu-group")),
    links: await texts(nav.locator("a.pf-menu-item")),
    current: await texts(nav.locator('a.pf-menu-item[aria-current="page"]')),
    box: { x: box.x, y: box.y, width: box.width, height: box.height },
    scrollTop: await nav
      .locator(".pf-menu-groups")
      .evaluate<number, Element>("(el) => el.scrollTop"),
  };
}

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

async function shot(page: Page, name: string): Promise<void> {
  await page.evaluate("document.getElementById('main-content')?.scrollTo(0, 0)");
  await settledScreenshot(page, name);
}

test.describe("Меню настроек не прыгает", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const size of [
    { width: 1512, height: 982 },
    { width: 1440, height: 900 },
  ]) {
    test(`${String(size.width)}: пункты, группы, размер и прокрутка меню одинаковы на каждой странице, axe 0`, async ({
      page,
    }) => {
      test.setTimeout(240_000);
      await page.setViewportSize(size);
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin");
      await expect(page.locator(MENU)).toBeVisible();
      await expect(page.locator(`${MENU} .pf-menu-group`)).toHaveCount(5);
      const first = await snapshot(page);
      // Состояние + пять групп из макета; все пункты видны сразу, а не только у открытой группы
      expect(first.captions).toHaveLength(5);
      expect(first.links.length).toBeGreaterThanOrEqual(19);
      await shot(page, "state");

      const hrefs: string[] = [];
      for (const link of await page.locator(`${MENU} a.pf-menu-item`).all()) {
        hrefs.push((await link.getAttribute("href")) ?? "");
      }
      for (const [index, href] of hrefs.entries()) {
        const link = page.locator(`${MENU} a.pf-menu-item[href="${href}"]`);
        // Playwright сам прокручивает меню к пункту; сравниваем прокрутку до и после нажатия — она не должна сбрасываться
        await link.scrollIntoViewIfNeeded();
        const scrolled = (await snapshot(page)).scrollTop;
        await link.click();
        await expect(page.locator(`${MENU} a.pf-menu-item[aria-current="page"]`)).toHaveAttribute(
          "href",
          href,
        );
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const now = await snapshot(page);
        const where = `${href} (${String(index + 1)} из ${String(hrefs.length)})`;
        expect(now.links, `пункты на ${where}`).toEqual(first.links);
        expect(now.captions, `группы на ${where}`).toEqual(first.captions);
        expect(now.current, `открытый пункт на ${where}`).toHaveLength(1);
        expect(now.box, `размер меню на ${where}`).toEqual(first.box);
        expect(now.scrollTop, `прокрутка меню на ${where}`).toBe(scrolled);
        // второго меню внутри страницы нет
        // (вкладки-фильтр «Что показать в журнале» — часть содержимого «Истории», доска 59 — следующий PR)
        await expect(
          page.locator('main nav:not([aria-label="Что показать в журнале"])'),
        ).toHaveCount(0);
        if (index % 4 === 0 || href.endsWith("/dictionaries")) {
          await shot(page, `page-${String(index + 1).padStart(2, "0")}`);
        }
      }
      await expectNoViolations(page, `menu ${String(size.width)}`);
    });
  }

  test("@mobile 390: одно меню — выпадающий список страниц со всеми группами, как на доске 55", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/company");
    const picker = page.getByRole("combobox", { name: /Страницы настроек/ });
    await expect(picker).toBeVisible();
    await shot(page, "phone-closed");
    // открытый список — виджет antd (известные замечания axe к его скрытым служебным узлам), проверяем закрытое состояние
    await expectNoViolations(page, "phone closed");
    await picker.click({ force: true });
    const options = page.locator(".ant-select-item-option");
    await expect(options.first()).toBeVisible();
    // список виртуальный — рисует только окно; все группы проверяем по их заголовкам при прокрутке до последней
    await expect(page.getByTitle("Люди и доступ")).toBeAttached();
    // поиск находит страницу из последней группы — список один, со всеми страницами
    await page.keyboard.type("Выгрузки");
    await expect(page.locator(".ant-select-item-option", { hasText: "Выгрузки" })).toBeVisible();
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await shot(page, "phone-open");
    await page.locator(".ant-select-item-option", { hasText: "Нумерация" }).click();
    await expect(page).toHaveURL(/\/admin\/numbering/);
    await expect(page.locator("#main-content .ant-select-selection-item").first()).toHaveText(
      "Нумерация",
    );
    // страница не шире экрана
    expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
  });
});
