import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// УВЕД-1: одно решение для уведомлений на MSW — всплывающее окно по подсказке потока, число на значках модулей, колокольчик
// с группами. Снимки — при `E2E_SCREENSHOT_DIR`.
const WIDTHS = [1512, 1440, 390] as const;
const QUOTE = {
  kind: "quote",
  number: "RFQ-1126-02",
  path: "/eds/drafts/RFQ-1126-02?panel=open&tab=approve",
} as const;

async function shot(page: Page, name: string, width: number): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png` });
}

async function push(page: Page, note: Record<string, unknown>): Promise<void> {
  await page.evaluate(`window.__rtMockPushNotification?.(${JSON.stringify(note)})`);
}

async function ready(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate("window.__rtMockStreamCount?.() ?? 0"), { timeout: 5_000 })
    .toBeGreaterThan(0);
  // первый список принят за «уже виденное»: накопленное не всплывает
  await expect
    .poll(() =>
      page.evaluate(
        `Object.keys(window.localStorage).some((k) => k.startsWith("rt-pf-notify-seen:"))`,
      ),
    )
    .toBe(true);
  await page.waitForTimeout(300);
}

test.describe("Уведомления: одно решение", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`пришло событие: окно с действием, открытие читает, бейдж модуля, группы в колокольчике, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await ready(page);
      await expect(page.getByRole("button", { name: /^Центр уведомлений, 3 новых/ })).toBeVisible();

      // 1. пришло уведомление «требует действия» — окно с одной кнопкой, остаётся на экране
      await push(page, {
        tab: "decisions",
        needs_action: true,
        title: "КП RFQ-1126-02 ждёт вашего согласования",
        subtitle: "АО «Демо-Рейл» · срок завтра",
        object: QUOTE,
      });
      const toast = page.locator(".ant-notification-notice", {
        hasText: "КП RFQ-1126-02 ждёт вашего согласования",
      });
      await expect(toast).toBeVisible();
      await expect(page.getByRole("button", { name: /^Центр уведомлений, 4 новых/ })).toBeVisible();
      await page.waitForTimeout(500);
      await shot(page, "toast", width);
      await expectNoViolations(page, `окно уведомления ${String(width)}`);

      // 2. значок модуля: одно правило — число там, где что-то требует действия
      await expect(
        page
          .getByRole("navigation", { name: "Модули" })
          .getByRole("link", {
            name: /требуют действия/,
          })
          .first(),
      ).toBeVisible();
      await shot(page, "rail", width);

      // 3. кнопка открывает объект, его уведомления прочитаны, окно закрыто
      await toast.getByRole("button", { name: "Открыть" }).click();
      await expect(page).toHaveURL(/\/eds\/drafts\/RFQ-1126-02/);
      await expect(page.getByRole("button", { name: /^Центр уведомлений, 3 новых/ })).toBeVisible();
      await expect(toast).toHaveCount(0);

      // 4. не показывается повторно после перезагрузки
      await page.reload();
      await expect(page.getByRole("button", { name: /^Центр уведомлений/ })).toBeVisible();
      await page.waitForTimeout(800);
      await expect(page.locator(".ant-notification-notice")).toHaveCount(0);
    });
  }

  test("колокольчик: события одного объекта — одна строка со счётчиком, раскрытие, «Требуют действия»", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await ready(page);
    for (const title of [
      "Пересчёт цены",
      "Клиент прокомментировал КП",
      "Шаг согласования вернулся",
    ]) {
      await push(page, { tab: "decisions", needs_action: true, title, object: QUOTE });
    }
    await push(page, { tab: "system", needs_action: false, title: "Сводка недели готова" });
    await expect(page.locator(".ant-notification-notice")).toHaveCount(3);

    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    const row = center.getByRole("link", { name: /RFQ-1126-02.*3 события/ });
    await expect(row).toBeVisible();
    await center.getByRole("button", { name: "Показать события" }).click();
    await expect(center.getByRole("link", { name: /Пересчёт цены/ })).toBeVisible();
    await waitForMotionEnd(page);
    await shot(page, "bell-groups", 1440);
    await expectNoViolations(page, "колокольчик с группами");

    // «Требуют действия»: сводка недели (к сведению) пропадает
    await expect(center.getByText("Сводка недели готова")).toBeVisible();
    await center.locator(".ant-segmented-item-label", { hasText: /^Требуют действия/ }).click();
    await expect(center.getByText("Сводка недели готова")).toHaveCount(0);

    // открытие объекта читает все его уведомления
    await center.getByRole("link", { name: /RFQ-1126-02.*3 события/ }).click();
    await expect(page).toHaveURL(/\/eds\/drafts\/RFQ-1126-02/);
  });

  test("настройки: окна можно выключить — уведомление в колокольчике, без окна", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "director@demo.example");
    await ready(page);
    await page.evaluate(
      `(() => { const id = Object.keys(window.localStorage).find((k) => k.startsWith("rt-pf-notify-seen:")).split(":")[1]; window.localStorage.setItem("rt-pf-notify-prefs:" + id, JSON.stringify({ popups: false })); window.dispatchEvent(new StorageEvent("storage")); })()`,
    );
    await push(page, { tab: "clients", needs_action: false, title: "Клиент открыл КП" });
    await expect(page.getByRole("button", { name: /^Центр уведомлений, 4 новых/ })).toBeVisible();
    await expect(page.locator(".ant-notification-notice")).toHaveCount(0);
  });
});
