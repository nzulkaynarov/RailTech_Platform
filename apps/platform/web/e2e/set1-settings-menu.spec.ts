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

async function expectNoViolations(
  page: Page,
  context: string,
  disabledRules: string[] = [],
): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .disableRules(disabledRules)
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

  test("прямой адрес последней страницы на 1440×790: открытый пункт меню виден без прокрутки руками", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 790 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/exports");
    const item = page.locator(`${MENU} a.pf-menu-item[aria-current="page"]`);
    await expect(item).toHaveAttribute("href", "/admin/exports");
    await expect(item).toBeInViewport({ ratio: 1 });
    await shot(page, "direct-exports");
  });

  test("1440×790: нажатие на наполовину скрытый пункт не прокручивает меню", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 790 });
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin");
    await expect(page.locator(`${MENU} .pf-menu-group`)).toHaveCount(5);
    // пункт, у которого видна только часть: нижний край списка режет его
    const href = await page.evaluate<string | null>(`(() => {
      const list = document.querySelector('${MENU} .pf-menu-groups');
      const edge = list.getBoundingClientRect().bottom;
      const cut = [...list.querySelectorAll('a.pf-menu-item')].find((a) => {
        const r = a.getBoundingClientRect();
        return r.top < edge - 4 && r.bottom > edge + 4;
      });
      return cut ? cut.getAttribute('href') : null;
    })()`);
    expect(href, "в меню должен быть наполовину скрытый пункт").not.toBeNull();
    const before = (await snapshot(page)).scrollTop;
    // настоящий щелчок без прокрутки Playwright к пункту
    await page.evaluate(
      `document.querySelector('${MENU} a.pf-menu-item[href="${href ?? ""}"]').dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))`,
    );
    await expect(page).toHaveURL(new RegExp(`${href ?? ""}$`));
    await expect(page.locator(`${MENU} a.pf-menu-item[aria-current="page"]`)).toHaveAttribute(
      "href",
      href ?? "",
    );
    expect((await snapshot(page)).scrollTop).toBe(before);
  });

  for (const size of [
    { width: 1280, height: 800 },
    { width: 1024, height: 768 },
  ]) {
    test(`${String(size.width)}×${String(size.height)}: всплывающее меню целиком достижимо, пункты как в меню; выбор над страницей в том же порядке`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin");
      await expect(page.locator(`${MENU} .pf-menu-group`)).toHaveCount(5);
      const menuLinks: string[] = [];
      for (const link of await page.locator(`${MENU} a.pf-menu-item`).all()) {
        menuLinks.push(
          `${(await link.innerText()).trim()}|${(await link.getAttribute("href")) ?? ""}`,
        );
      }
      await page.setViewportSize(size);
      await spaGoto(page, "/crm/clients");
      await page
        .getByRole("navigation", { name: "Модули" })
        .getByRole("link", { name: "Настройки" })
        .hover();
      const flyout = page.locator(".ant-popover:not(.ant-popover-hidden)");
      await expect(flyout.locator("a.pf-menu-item").first()).toBeVisible();
      const flyLinks: string[] = [];
      for (const link of await flyout.locator("a.pf-menu-item").all()) {
        flyLinks.push(
          `${(await link.innerText()).trim()}|${(await link.getAttribute("href")) ?? ""}`,
        );
      }
      expect(flyLinks).toEqual(menuLinks);
      // меню помещается в экран: не ниже окна и первый, и последний пункт видны (после прокрутки внутри)
      const box = await flyout.locator(".ant-popover-inner").boundingBox();
      expect(box && box.y >= 0 && box.y + box.height <= size.height, "окно в пределах экрана").toBe(
        true,
      );
      await flyout.locator("a.pf-menu-item").last().scrollIntoViewIfNeeded();
      await expect(flyout.locator("a.pf-menu-item").last()).toBeInViewport({ ratio: 1 });
      await expect(flyout.locator("a.pf-menu-item").first().locator("..")).toBeAttached();
      await shot(page, `flyout-${String(size.width)}`);

      // выбор над страницей (меню свёрнуто): те же названия в том же порядке
      await page.keyboard.press("Escape");
      await spaGoto(page, "/admin/company");
      await page.locator("#pf-set-frame-nav").click({ force: true });
      const options: string[] = [];
      for (const option of await page.locator(".ant-select-item-option").all()) {
        options.push(((await option.getAttribute("title")) ?? "").trim());
      }
      expect(options).toEqual(menuLinks.map((entry) => entry.split("|")[0] ?? ""));
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
    await expectNoViolations(page, "phone closed");
    await picker.click({ force: true });
    const options = page.locator(".ant-select-item-option");
    await expect(options.first()).toBeVisible();
    // список не виртуальный (virtual={false}): все группы в разметке
    await expect(page.getByTitle("Люди и доступ")).toBeAttached();
    // поиск находит страницу из последней группы — список один, со всеми страницами
    await page.keyboard.type("Выгрузки");
    await expect(page.locator(".ant-select-item-option", { hasText: "Выгрузки" })).toBeVisible();
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await shot(page, "phone-open");
    // Прокручиваемый список antd не берёт фокус сам (правило scrollable-region-focusable); с клавиатуры список листается
    // стрелками из поля выбора, поэтому на открытом списке исключено только это правило.
    await expectNoViolations(page, "phone open", ["scrollable-region-focusable"]);
    await page.locator(".ant-select-item-option", { hasText: "Нумерация" }).click();
    await expect(page).toHaveURL(/\/admin\/numbering/);
    await expect(page.locator("#main-content .ant-select-selection-item").first()).toHaveText(
      "Нумерация",
    );
    // страница не шире экрана
    expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
  });
});
