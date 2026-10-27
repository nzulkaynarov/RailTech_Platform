import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// W13-A6 на MSW: сброс пароля по почте, журнал аудита (кто, что, когда), вкладка «Журнал» роли, профиль и уведомления.
// Каждое действие — сценарием глазами; axe 0 и снимки 1440 и 390 px.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";

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

async function tallScreenshot(page: Page, name: string): Promise<void> {
  const width = page.viewportSize()?.width ?? 1440;
  await page.setViewportSize({ width, height: 1300 });
  await settledScreenshot(page, name);
  await page.setViewportSize({ width, height: 900 });
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe("Журнал аудита", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам тест");

  test("админ фильтрует журнал, открывает запись и видит, что изменилось", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/audit");
    await expect(page.getByRole("heading", { level: 1, name: "Журнал аудита" })).toBeVisible();
    const table = page.getByRole("table", { name: "Записи журнала аудита" });
    await expect(table.getByRole("row")).toHaveCount(14);
    await expect(page.getByText("Записей: 13")).toBeVisible();
    await settledScreenshot(page, "audit-list");

    // Входы по умолчанию скрыты.
    await page.getByRole("switch", { name: "Показывать входы в систему" }).click();
    await expect(page.getByText("Записей: 15")).toBeVisible();
    await page.getByRole("switch", { name: "Показывать входы в систему" }).click();
    await expect(page.getByText("Записей: 13")).toBeVisible();

    // Фильтр по объекту и периоду.
    await page.getByLabel("Объект").click();
    await page.getByTitle("Роль Платформы").click();
    await expect(page.getByText("Записей: 2")).toBeVisible();
    await page.getByLabel("С даты").fill("2026-10-24");
    await expect(page.getByText("Записей: 1")).toBeVisible();
    await page.getByLabel("С даты").fill("2026-12-01");
    await expect(page.getByText("По этим фильтрам записей нет")).toBeVisible();
    await page.getByRole("button", { name: "Сбросить фильтры" }).first().click();
    await expect(page.getByText("Записей: 13")).toBeVisible();

    // Запись: кто, когда, что изменилось.
    await page
      .getByRole("link", { name: /Открыть запись: Изменил сотрудника, 25\.10\.2026/ })
      .click();
    const side = page.locator(PANEL);
    await expect(side.getByRole("heading", { level: 3, name: "Изменил сотрудника" })).toBeVisible();
    await expect(side.getByText("Менеджер, Снабженец")).toBeVisible();
    await expect(side.getByText("Демо Админов")).toBeVisible();
    await settledScreenshot(page, "audit-entry");
  });

  test("запись об изменении роли показывает разделы словами; секреты не видны", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/audit?entry=116&panel=open");
    const side = page.locator(PANEL);
    await expect(side.getByText(/Все запросы, Расчёт: Скрыто → Только чтение/)).toBeVisible();
    await expect(side.getByText(/Поле «Цены поставщиков»: станет видно/)).toBeVisible();

    await spaGoto(page, "/admin/audit?entry=119&panel=open");
    await expect(side.getByRole("heading", { level: 3, name: /Настроил коннектор/ })).toBeVisible();
    await expect(side.getByText("smtp.demo.example")).toBeVisible();
  });

  test("директор читает журнал; менеджеру раздела нет", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/audit");
    await expect(
      page.getByRole("table", { name: "Записи журнала аудита" }).getByRole("row"),
    ).toHaveCount(14);
    await signOut(page);

    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/admin/audit");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });

  for (const width of WIDTHS) {
    test(`журнал на ${String(width)} px: без горизонтальной прокрутки, axe 0`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/audit");
      await expect(page.getByText("Записей: 13")).toBeVisible();
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await expectNoViolations(page, `журнал ${String(width)}`);
      await settledScreenshot(page, "audit-list");

      await spaGoto(page, "/admin/audit?entry=118&panel=open");
      await expect(
        page.locator(PANEL).getByRole("heading", { level: 3, name: "Изменил сотрудника" }),
      ).toBeVisible();
      await expectNoViolations(page, `запись ${String(width)}`);
      await settledScreenshot(page, "audit-entry");
    });
  }
});

test.describe("Роль: вкладка «Журнал»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам тест");

  test("сохранение роли попадает в журнал роли: кто, когда, что", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/roles?role=3&panel=open&tab=role");
    const side = page.locator(PANEL);
    await side.getByLabel("Название").fill("Менеджер продаж");
    await side.getByRole("button", { name: "Сохранить роль" }).click();
    await expect(page.getByText("Роль сохранена")).toBeVisible();

    await side.getByRole("tab", { name: "Журнал" }).click();
    await expect(
      side.getByRole("heading", { level: 3, name: "Журнал роли «Менеджер продаж»" }),
    ).toBeVisible();
    await expect(side.getByText("Название: «Менеджер» → «Менеджер продаж»")).toBeVisible();
    await expect(side.getByText(/· Демо Админов/).first()).toBeVisible();
    await expect(side.getByText("Создана роль «Менеджер»")).toBeVisible();
  });

  test("директор видит журнал роли только для чтения", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/roles?role=3&panel=open&tab=journal");
    await expect(page.locator(PANEL).getByText("Создана роль «Менеджер»")).toBeVisible();
  });

  for (const width of WIDTHS) {
    test(`журнал роли на ${String(width)} px: axe 0`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/roles?role=3&panel=open&tab=journal");
      await expect(page.locator(PANEL).getByText("Создана роль «Менеджер»")).toBeVisible();
      await expectNoViolations(page, `журнал роли ${String(width)}`);
      await settledScreenshot(page, "role-journal");
    });
  }
});

test.describe("Сброс пароля сотрудника", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам тест");

  test("админ сбрасывает пароль по почте; себе сбросить нельзя", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
    const side = page.locator(PANEL);
    await expect(side.getByRole("heading", { level: 3, name: "Демо Менеджеров" })).toBeVisible();

    await side.getByRole("button", { name: "Сбросить пароль" }).click();
    const reset = side.getByRole("group", { name: "Сброс пароля" });
    await expect(reset.getByText("Что произойдёт")).toBeVisible();
    await expect(reset.getByText(/Сотрудник получит письмо на manager@demo.example/)).toBeVisible();
    await expect(reset.getByRole("radio", { name: "Временным паролем" })).toBeEnabled();
    await tallScreenshot(page, "org-reset-password");

    await side.getByRole("button", { name: "Сбросить и отправить письмо" }).click();
    await expect(
      page.getByText("Письмо с новым паролем отправлено на manager@demo.example"),
    ).toBeVisible();

    // Действие записано в журнал.
    await spaGoto(page, "/admin/audit");
    await expect(
      page
        .getByRole("link", { name: /Открыть запись: Сбросил пароль и отправил по почте/ })
        .first(),
    ).toBeVisible();

    // Себе — нельзя.
    await spaGoto(page, "/admin/org?employee=u-demo-admin&panel=open");
    await expect(
      page.locator(PANEL).getByRole("heading", { level: 3, name: "Демо Админов" }),
    ).toBeVisible();
    await expect(
      page.locator(PANEL).getByRole("button", { name: "Сбросить пароль" }),
    ).toBeDisabled();
    await expect(page.locator(PANEL).getByText(/Свой пароль здесь не сбросить/)).toBeVisible();
  });

  test("админ выдаёт временный пароль без почты: пароль виден один раз, действие в журнале", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
    const side = page.locator(PANEL);
    await expect(side.getByRole("heading", { level: 3, name: "Демо Менеджеров" })).toBeVisible();

    await side.getByRole("button", { name: "Сбросить пароль" }).click();
    const reset = side.getByRole("group", { name: "Сброс пароля" });
    await reset.getByRole("radio", { name: "Временным паролем" }).check();
    await expect(reset.getByText(/Прежний пароль перестанет действовать/)).toBeVisible();
    await tallScreenshot(page, "org-temporary-password-confirm");
    await reset.getByRole("button", { name: "Выдать пароль" }).click();

    const password = side.getByRole("textbox", { name: "Временный пароль" });
    await expect(password).toHaveValue(/^Tmp-/);
    await settledScreenshot(page, "org-temporary-password");
    await side.getByRole("button", { name: "Готово: пароль передан" }).click();
    await expect(side.getByRole("textbox", { name: "Временный пароль" })).toHaveCount(0);
    await expect(side.getByRole("button", { name: "Сбросить пароль" })).toBeVisible();

    await spaGoto(page, "/admin/audit");
    await expect(
      page.getByRole("link", { name: /Открыть запись: Сбросил пароль, / }).first(),
    ).toBeVisible();
  });

  test("директору кнопки сброса нет", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
    await expect(
      page.locator(PANEL).getByRole("heading", { level: 3, name: "Демо Менеджеров" }),
    ).toBeVisible();
    await expect(page.locator(PANEL).getByRole("button", { name: "Сбросить пароль" })).toHaveCount(
      0,
    );
  });

  for (const width of WIDTHS) {
    test(`сброс пароля на ${String(width)} px: axe 0`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
      const side = page.locator(PANEL);
      await side.getByRole("button", { name: "Сбросить пароль" }).click();
      await expect(
        side.getByRole("group", { name: "Сброс пароля" }).getByText("Что произойдёт"),
      ).toBeVisible();
      await expectNoViolations(page, `сброс пароля ${String(width)}`);
      await tallScreenshot(page, "org-reset-password");
      await side
        .getByRole("group", { name: "Сброс пароля" })
        .getByRole("radio", { name: "Временным паролем" })
        .check();
      await expectNoViolations(page, `временный пароль ${String(width)}`);
      await tallScreenshot(page, "org-temporary-password-confirm");
    });
  }
});

test.describe("Профиль: уведомления", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам тест");

  test("сотрудник меняет подписку и отправляет тестовое уведомление", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    const dialog = page.getByRole("dialog", { name: "Профиль" });
    await expect(dialog.getByRole("heading", { name: "Уведомления" })).toBeVisible();
    await expect(dialog.getByText("Привязан")).toBeVisible();

    const leads = dialog.getByRole("switch", { name: "Лиды, которые ждут меня" });
    await expect(leads).toBeChecked();
    await leads.click();
    await expect(leads).not.toBeChecked();

    await dialog.getByRole("button", { name: "Тестовое уведомление" }).click();
    await expect(page.getByText("Тестовое сообщение отправлено в Telegram")).toBeVisible();
  });

  test("Telegram не привязан и доставка не удалась — словами", async ({ page }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    const dialog = page.getByRole("dialog", { name: "Профиль" });
    await expect(dialog.getByText("Не привязан", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Тестовое уведомление" })).toBeDisabled();
    await page.locator(".ant-modal-close").click();
    await expect(dialog).toBeHidden();
    await signOut(page);

    await loginAndWait(page, "accountant@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    await expect(
      page.getByRole("dialog", { name: "Профиль" }).getByText(/Последнее сообщение бота не дошло/),
    ).toBeVisible();
  });

  for (const width of WIDTHS) {
    test(`профиль на ${String(width)} px: axe 0`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: "Профиль" }).click();
      const dialog = page.getByRole("dialog", { name: "Профиль" });
      await expect(dialog.getByRole("switch", { name: "Системные оповещения" })).toBeVisible();
      await expectNoViolations(page, `профиль ${String(width)}`);
      await settledScreenshot(page, "profile-notifications");
    });
  }
});
