import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// UX-1b «Шапка, бар несохранённого, поиск» (аудит 2026-10-30, S5–S7, S13, S16, A1): поиск стоит на одном x во всех
// разделах и при открытии окна; бар несохранённого держит место в конце формы — первый символ ничего не сдвигает; уход
// с правками спрашивает; иконки результатов поиска — в своих строках. axe 0 и снимки (`E2E_SCREENSHOT_DIR=docs/screens/ux-1b`).

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

// Поле в фокусе не под баром: центр его рамки виден и в этой точке не бар. «bar» — фокус дошёл до кнопок бара,
// «done» — ушёл из формы с баром.
const FOCUS_STATE = `(() => {
  const a = document.activeElement;
  const dock = document.querySelector(".pf-save-dock");
  if (!a || !dock) return "done";
  if (a.closest(".pf-save-bar")) return "bar";
  if (!dock.parentElement.contains(a)) return "done";
  const box = (a.closest(".ant-select, .ant-picker, .ant-input-affix-wrapper") || a).getBoundingClientRect();
  if (box.width === 0 || box.height === 0) return "ok";
  const x = box.left + box.width / 2;
  const y = box.top + box.height / 2;
  const hit = document.elementFromPoint(x, y);
  if (!hit) return "вне экрана: " + (a.id || a.tagName) + " y=" + Math.round(y);
  if (hit.closest(".pf-save-bar")) return "под баром: " + (a.id || a.tagName);
  return "ok";
})()`;

async function tabThroughForm(page: Page, first: Locator): Promise<number> {
  await first.focus();
  let checked = 0;
  for (let step = 0; step < 25; step += 1) {
    await page.waitForTimeout(120);
    const state = await page.evaluate<string>(FOCUS_STATE);
    if (state === "bar" || state === "done") break;
    expect(state, `поле №${String(step + 1)}`).toBe("ok");
    checked += 1;
    await page.keyboard.press("Tab");
  }
  return checked;
}

const searchX = (page: Page) =>
  page.evaluate<number>(`document.querySelector(".pf-gsearch").getBoundingClientRect().x`);
// Положение в прокручиваемой области (y + scrollTop): прокрутка к полю над баром — не сдвиг вёрстки.
const top = (page: Page, selector: string) =>
  page.evaluate<number>(
    `Math.round(document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect().y + document.getElementById("main-content").scrollTop)`,
  );

test.describe("Шапка и бар несохранённого", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 1280] as const) {
    test(`${String(width)}: поиск на одном x — разделы, /me, окно открыто и закрыто`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "all@demo.example");
      await spaGoto(page, "/eds/inbox");
      await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
      const x = await searchX(page);

      const toggle = page.getByRole("button", { name: "Показать панель" });
      await expect(toggle).toBeVisible();
      if (width === 1440) await settledScreenshot(page, "header-panel-closed");
      await toggle.click();
      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toBeVisible();
      expect(await searchX(page)).toBe(x);
      if (width === 1440) {
        await page.mouse.move(10, 400);
        await settledScreenshot(page, "header-panel-open");
      }
      await page.getByRole("button", { name: "Скрыть панель" }).click();
      expect(await searchX(page)).toBe(x);

      // Раздел без окна: кнопка невидима, но держит место
      await spaGoto(page, "/me");
      await expect(page.getByRole("heading", { level: 1, name: "Профиль" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Показать панель" })).toHaveCount(0);
      expect(await searchX(page)).toBe(x);
      await spaGoto(page, "/help");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await searchX(page)).toBe(x);
    });
  }

  for (const width of [1440, 390] as const) {
    test(`${String(width)}: Профиль — бар на месте, форма не сдвигается, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/me");
      const data = page.getByRole("region", { name: "Личные данные" });
      const name = data.getByRole("textbox", { name: "Имя" });
      await expect(name).toBeVisible();
      await expect(data.getByRole("button", { name: "Сохранить", exact: true })).toBeHidden();

      const formTop = await top(page, '[data-testid="profile-data"] form');
      const nameTop = await top(
        page,
        '[data-testid="profile-data"] input#name, [data-testid="profile-data"] input[autocomplete="name"]',
      );
      await name.pressSequentially("я");
      const save = data.getByRole("button", { name: "Сохранить", exact: true });
      await expect(save).toBeVisible();
      await page.waitForTimeout(120);
      expect(await page.evaluate<string>(FOCUS_STATE), "поле ввода над баром").toBe("ok");
      expect(await top(page, '[data-testid="profile-data"] form')).toBe(formTop);
      expect(
        await top(
          page,
          '[data-testid="profile-data"] input#name, [data-testid="profile-data"] input[autocomplete="name"]',
        ),
      ).toBe(nameTop);
      // бар — в окне просмотра, над нижней панелью модулей на телефоне
      const bar = await save.boundingBox();
      expect((bar?.y ?? 0) + (bar?.height ?? 0)).toBeLessThanOrEqual(
        width === 390 ? 844 - 60 : 900,
      );
      await settledScreenshot(page, "profile-savebar");
      await expectNoViolations(page, "Профиль, бар");
      // Tab по полям: ни одно поле в фокусе не уходит под бар
      expect(await tabThroughForm(page, name)).toBeGreaterThanOrEqual(4);

      // уход с правками — вопрос; «Остаться» оставляет правку
      await page.getByRole("navigation", { name: "Модули" }).getByRole("link").first().click();
      const dialog = page.getByRole("dialog", { name: "Выйти без сохранения?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Остаться" }).click();
      await expect(page).toHaveURL(/\/me$/);
      await expect(name).toHaveValue(/я/);
    });

    test(`${String(width)}: Компания — бар вместо второй кнопки, вкладка с правками спрашивает, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/admin/company?tab=details");
      await expect(
        page.getByRole("heading", { level: 2, name: "Реквизиты компании" }),
      ).toBeVisible();
      const save = page.getByRole("button", { name: "Сохранить реквизиты" });
      await expect(save).toBeHidden();

      await page.getByLabel("Телефон").fill("+998 11 111 11 11");
      await expect(save).toBeVisible();
      await expect(page.getByRole("button", { name: "Сохранить реквизиты" })).toHaveCount(1);
      await settledScreenshot(page, "company-savebar");
      await expectNoViolations(page, "Компания, бар");
      // Tab по полям реквизитов: ни одно поле в фокусе не уходит под бар
      expect(
        await tabThroughForm(page, page.getByLabel("Полное наименование")),
      ).toBeGreaterThanOrEqual(8);
      await page.getByLabel("Телефон").focus();

      await page.getByRole("tab", { name: "Бланк и бренд" }).click();
      const dialog = page.getByRole("dialog", { name: "Выйти без сохранения?" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Остаться" }).click();
      await expect(page.getByLabel("Телефон")).toHaveValue("+998 11 111 11 11");
      await page.getByRole("button", { name: "Отменить" }).click();
      await expect(save).toBeHidden();
      await page.getByRole("tab", { name: "Бланк и бренд" }).click();
      await expect(
        page.getByRole("heading", { level: 2, name: "Бланк и бренд документов" }),
      ).toBeVisible();
    });
  }

  test("1440: поиск «док» — иконки разделов в своих строках, axe 0", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "all@demo.example");
    const field = page.getByRole("combobox", { name: "Глобальный поиск" });
    await field.click();
    await field.pressSequentially("док");
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible();
    const inside = await page.evaluate<
      boolean[]
    >(`[...document.querySelectorAll('.pf-gsearch-pop [role="option"]')]
      .filter((o) => o.querySelector(".pf-gsearch-result-icon"))
      .map((o) => { const a = o.getBoundingClientRect(); const b = o.querySelector(".pf-gsearch-result-icon").getBoundingClientRect();
        return b.y >= a.y - 1 && b.bottom <= a.bottom + 1; })`);
    expect(inside.length).toBeGreaterThan(0);
    expect(inside.every(Boolean)).toBe(true);
    await settledScreenshot(page, "search-dropdown");
    await expectNoViolations(page, "поиск");
  });

  test("390: шторка уведомлений без переполнения, axe 0", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const drawer = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("radio", { name: /^Непрочитанные/ })).toBeChecked();
    const overflow = await page.evaluate<number>(
      `(() => { const d = document.querySelector(".ant-drawer-content"); return d.scrollWidth - d.clientWidth; })()`,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await settledScreenshot(page, "notifications-drawer");
    await expectNoViolations(page, "шторка");
  });
});
