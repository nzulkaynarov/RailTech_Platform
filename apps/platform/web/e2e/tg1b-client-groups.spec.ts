import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ТГ-1б на MSW (ADR-0032): Настройки · Telegram · «Группы с клиентами» (список с состояниями, привязка кодом, отключение
// с подтверждением) и раздел «Группа с клиентом» в карточке клиента с лентой группы (только чтение). Снимки 1512, 1440 и 390
// с axe; страница не ползёт вбок.
const dir = process.env["E2E_SCREENSHOT_DIR"];
const WIDTHS = [1512, 1440, 390] as const;

async function size(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
}

async function expectNoSideScroll(page: Page): Promise<void> {
  const over = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(over).toBeLessThanOrEqual(0);
}

for (const width of WIDTHS) {
  test(`настройки: группы с клиентами, ${String(width)}`, { tag: "@mobile" }, async ({ page }) => {
    test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
    await size(page, width);
    await loginAndWait(page, "all@demo.example");
    await spaGoto(page, "/admin/telegram?tab=groups");
    const list = page.getByRole("list").filter({ hasText: "Рельс-Сервис · заявки" });
    await expect(list.getByText("Подключена", { exact: true })).toBeVisible();
    await expect(list.getByText("Ждёт кода", { exact: true })).toBeVisible();
    await expect(list.getByText("Нужны права администратора", { exact: true })).toBeVisible();
    await expect(list.getByText("Код истёк", { exact: true }).first()).toBeVisible();
    await waitForMotionEnd(page);
    await expectNoSideScroll(page);
    if (dir)
      await page.screenshot({
        path: `${dir}/settings-groups-${String(width)}.png`,
        fullPage: true,
      });
    await expectNoViolations(page, "настройки: группы с клиентами");

    // Привязка: код + клиент → «Подключить»; ждущая группа становится подключённой
    await page.getByLabel("Код из группы").fill("K7M2QX");
    await page.getByRole("combobox", { name: "Клиент" }).click();
    await page.locator(".ant-select-item-option").first().click();
    await page.getByRole("button", { name: "Подключить" }).click();
    await expect(page.getByText("Ждёт кода", { exact: true })).toBeHidden();

    // Отключение — с подтверждением
    await page.getByRole("button", { name: "Отключить группу Рельс-Сервис · заявки" }).click();
    const dialog = page.getByRole("dialog", { name: "Отключить группу?" });
    await expect(dialog).toBeVisible();
    await waitForMotionEnd(page);
    if (dir) await page.screenshot({ path: `${dir}/settings-confirm-${String(width)}.png` });
    await dialog.getByRole("button", { name: "Отключить", exact: true }).click();
    await expect(page.getByText("Отключена", { exact: true })).toBeVisible();
  });

  test(
    `карточка клиента: группа с клиентом, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await size(page, width);
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
      await page.getByRole("tab", { name: "Заявки и проекты" }).click();
      const section = page.getByRole("region", { name: "Группа с клиентом" });
      await expect(section.getByText("Рельс-Сервис · заявки")).toBeVisible();
      await expect(section.getByText("Подключена", { exact: true })).toBeVisible();
      // Лента скрыта, пока её не открыли; ответа из Платформы нет
      await expect(page.getByRole("textbox", { name: /Ответ/ })).toHaveCount(0);
      await section.getByRole("button", { name: "Переписка группы" }).click();
      await expect(section.getByText("Накладная-0042.pdf")).toBeVisible();
      await expect(section.getByText("Наш сотрудник")).toBeVisible();
      await expect(
        section.getByText("Чертёж-узла.zip — файл больше 20 МБ — откройте в группе"),
      ).toBeVisible();
      await expect(section.getByText("Ответить можно в самой группе.")).toBeVisible();
      // Карточка прокручивается внутри окна: снимок — на разделе с лентой
      const feed = section.getByRole("region", { name: "Переписка с Рельс-Сервис · заявки" });
      await feed.scrollIntoViewIfNeeded();
      await expect(feed).toBeInViewport();
      await waitForMotionEnd(page);
      await expectNoSideScroll(page);
      if (dir) await page.screenshot({ path: `${dir}/card-group-${String(width)}.png` });
      await expectNoViolations(page, "карточка клиента: группа с клиентом");
    },
  );
}

test("клиент без группы: раздела нет", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "manager@demo.example");
  await spaGoto(page, "/crm/clients/5?panel=open&tab=card");
  await expect(page.getByRole("heading", { name: "Контакты" }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Группа с клиентом" })).toHaveCount(0);
});
