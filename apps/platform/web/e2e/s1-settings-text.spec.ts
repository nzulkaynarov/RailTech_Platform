import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// S1–S5 «Настройки: короче и без дублей» (ресёрч 2026-11-02 «Настройки» §4.2, §5): у сохранения настроек нет «Что
// произойдёт», подзаголовки — одна строка без названий систем, в «Подключениях» карточки выше «Требует внимания» и
// одинаковые причины — одной строкой, в боте — ссылки вместо дублей. Снимки 1440 и 390 и axe 0 —
// `E2E_SCREENSHOT_DIR=docs/screens/s1`.

/** Подзаголовок страницы: одна строка, без CRM/ERP/EDS и «ансамбля» — или его нет (CONVENTIONS §2 п. 17). */
async function expectShortSubtitle(page: Page, context: string): Promise<void> {
  const subtitles = page.locator("main h1 + div");
  if ((await subtitles.count()) === 0) return;
  const text = (await subtitles.first().textContent()) ?? "";
  expect(text.length, `${context}: «${text}»`).toBeLessThanOrEqual(90);
  expect(text, context).not.toMatch(/\b(CRM|ERP|EDS)\b|ансамбл|бэк-офис/);
}

test.describe("S1 · Настройки короче", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`администратор на ${String(width)}: подзаголовки, «Подключения», бот и компания — без лишнего, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      // «Подключения»: карточки выше «Требует внимания», одинаковые причины — одной строкой
      await spaGoto(page, "/admin/integrations");
      await expect(page.getByRole("heading", { level: 1, name: "Подключения" })).toBeVisible();
      const cards = page.getByRole("heading", { level: 2, name: "Сервисы" });
      const attention = page.getByRole("heading", { level: 2, name: "Требует внимания" });
      await expect(attention).toBeVisible();
      const cardsTop = (await cards.boundingBox())?.y ?? 0;
      const attentionTop = (await attention.boundingBox())?.y ?? 0;
      expect(cardsTop).toBeLessThan(attentionTop);
      const details = await page
        .locator("section:has(#pf-int-attention) li[data-group] .pf-int-sub")
        .allTextContents();
      expect(new Set(details).size, "одинаковые причины — одной строкой").toBe(details.length);
      await expectShortSubtitle(page, "Подключения");
      await settledScreenshot(page, "s1-integrations");
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await page.screenshot({
          path: `${dir}/s1-integrations-full-${String(width)}.png`,
          fullPage: true,
        });
      }
      await expectNoViolations(page, `Подключения ${String(width)}`);

      // «Компания» бота — «Контакты для клиентов» на странице «Реквизиты и бланк» (SET-IA): одно место вместо ссылки-дубля,
      // без «Что произойдёт»
      await spaGoto(page, "/admin/bot?part=behavior&section=company");
      await expect(
        page.getByRole("heading", { level: 1, name: "Реквизиты и бланк" }),
      ).toBeVisible();
      const contacts = page.getByRole("region", { name: "Контакты для клиентов", exact: true });
      await expect(contacts.getByLabel("Название компании")).toBeVisible();
      await contacts.scrollIntoViewIfNeeded();
      await expect(contacts.getByRole("group", { name: "Что произойдёт" })).toHaveCount(0);
      await expect(page.getByRole("link", { name: /Реквизиты для документов —/ })).toHaveCount(0);
      await expectShortSubtitle(page, "Реквизиты и бланк");
      await settledScreenshot(page, "s1-bot-company");
      await expectNoViolations(page, `Бот ${String(width)}`);

      // «Компания · Нумерация»: строка-пояснение вместо блока
      await spaGoto(page, "/admin/company?tab=numbering");
      await page.getByLabel("Ширина счётчика").fill("6");
      await expect(
        page.getByText("Новые номера пойдут по этой схеме; выданные не меняются."),
      ).toBeVisible();
      await expect(page.getByRole("group", { name: "Что произойдёт" })).toHaveCount(0);
      await expectShortSubtitle(page, "Нумерация");
      await settledScreenshot(page, "s1-company-numbering");
      await expectNoViolations(page, `Компания ${String(width)}`);
      await page.getByRole("button", { name: "Отменить" }).click();

      // «Первый запуск», «Роли и права», «Сотрудники»: подзаголовок — одна строка
      for (const [path, title, name] of [
        ["/admin/setup", "Первый запуск", "s1-setup"],
        ["/admin", "Все настройки", "s1-index"],
        ["/admin/roles", "Роли и права", "s1-roles"],
        ["/admin/org", "Сотрудники", "s1-org"],
      ] as const) {
        await spaGoto(page, path);
        await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
        await expectShortSubtitle(page, title);
        await settledScreenshot(page, name);
        await expectNoViolations(page, `${title} ${String(width)}`);
      }
    });
  }
});
