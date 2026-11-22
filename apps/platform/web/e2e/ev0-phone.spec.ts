import { expect, test, type Page } from "@playwright/test";

import {
  confirmDialog,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
} from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЕВ-0 «Гигиена телефона»: нижняя панель без «Настроек», touch-цели 44 px, клавиатура, согласование директора с телефона,
// ширины 390 / 768 / 1024 без горизонтальной прокрутки. Проект mobile (Pixel 7) — указатель coarse, как на телефоне.
test.describe("Гигиена телефона @mobile", () => {
  test.skip(({ isMobile }) => !isMobile, "нужен coarse-указатель: проект mobile");

  const widths = [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
  ];

  for (const size of widths) {
    test(`@mobile ${String(size.width)}: главные экраны без горизонтальной прокрутки`, async ({
      page,
    }) => {
      await page.setViewportSize(size);
      await loginAndWait(page, "director@demo.example");
      for (const route of ["/dashboard/queue", "/eds/inbox", "/eds/approvals", "/erp/calc"]) {
        await spaGoto(page, route);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const overflow = await page.evaluate(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        );
        expect(overflow, `${route} @${String(size.width)}`).toBeLessThanOrEqual(0);
      }
      await settledScreenshot(page, `queue-${String(size.width)}`);
    });
  }

  test("@mobile 390: в нижней панели нет «Настроек», они в меню профиля; кнопки 44 px", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    const bar = page.getByRole("navigation", { name: "Модули" });
    await expect(bar.getByRole("link", { name: /Настройки/ })).toHaveCount(0);
    expect(await bar.getByRole("link").count()).toBeLessThanOrEqual(5);

    for (const target of await bar.locator("a, button").all()) {
      const box = await target.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    }
    await settledScreenshot(page, "bottom-bar");

    await openAvatarMenu(page);
    const settings = page.getByRole("menuitem", { name: "Настройки" });
    await expect(settings).toBeVisible();
    await settledScreenshot(page, "profile-menu");
    await settings.click();
    await expect(page).toHaveURL(/\/admin/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("@mobile 390: ссылка из очереди на одобрение КП — читать и решить, кнопки над клавиатурой", async ({
    page,
  }) => {
    // Экранная клавиатура: visualViewport подменён, window.__kb(px) «открывает» её
    await page.addInitScript(`(() => {
      const vv = Object.assign(new EventTarget(), { height: window.innerHeight, offsetTop: 0 });
      Object.defineProperty(window, "visualViewport", { value: vv, configurable: true });
      window.__kb = (h) => { vv.height = window.innerHeight - h; vv.dispatchEvent(new Event("resize")); };
    })()`);
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}?panel=open&tab=approve`);
    const sheet = page.getByRole("dialog", { name: /^Одобрение/ });
    await expect(sheet.getByRole("form", { name: "Одобрение КП" })).toBeVisible();

    const approve = sheet.getByRole("button", { name: "Одобрить КП" });
    const back = sheet.getByRole("button", { name: "Вернуть на доработку" });
    await expect(approve).toBeInViewport();
    await expect(back).toBeInViewport();
    expect(await page.evaluate("document.documentElement.scrollWidth")).toBeLessThanOrEqual(390);
    for (const button of [approve, back]) {
      expect((await button.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    // решение не перекрыто нижней панелью или чем-то ещё: пробный клик доходит до самой кнопки
    await approve.click({ trial: true });
    await settledScreenshot(page, "approval-390");

    // экранная клавиатура 320 px: лист поднят над ней, кнопки на виду, панель модулей скрыта
    await page.evaluate("window.__kb(320)");
    await expect(page.locator("html")).toHaveAttribute("data-kb", "open");
    await expect(page.getByRole("navigation", { name: "Модули" })).toBeHidden();
    const sheetBox = await sheet.boundingBox();
    expect((sheetBox?.y ?? 0) + (sheetBox?.height ?? 0)).toBeLessThanOrEqual(844 - 320 + 1);
    await expect(approve).toBeInViewport();
    await settledScreenshot(page, "approval-keyboard");
    await page.evaluate("window.__kb(0)");
    await expect(page.locator("html")).not.toHaveAttribute("data-kb", "open");
    await expectNoViolations(page, "телефон: одобрение КП");
  });

  test("@mobile 390: служебка — читать и согласовать без горизонтальной прокрутки", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/approvals/${encodeURIComponent("СЗ-2026/014")}`);
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/014" })).toBeVisible();
    expect(
      await page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      ),
    ).toBeLessThanOrEqual(0);
    await settledScreenshot(page, "memo-390");
    await spaGoto(page, `/eds/approvals/${encodeURIComponent("СЗ-2026/014")}?panel=open&tab=agree`);
    const sheet = page.getByRole("dialog", { name: /^Согласование/ });
    const agree = sheet.getByRole("button", { name: "Согласовать" });
    await expect(agree).toBeInViewport();
    expect((await agree.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    await agree.click();
    await confirmDialog(page);
    await expect(page.getByText("Документ согласован", { exact: true }).first()).toBeVisible();
  });

  test("@mobile 768: нижняя панель и лист, снимок", async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    await settledScreenshot(page, "quote-768");
  });
});
