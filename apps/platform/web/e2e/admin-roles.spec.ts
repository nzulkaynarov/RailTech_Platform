import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  login,
  openAvatarMenu,
  railLinks,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// Admin · Ролевая матрица на MSW (R-2, ADR-0012): роли — данные. Админ создаёт роль «Менеджер и бухгалтер», выдаёт её
// сотруднику, тот после входа видит ровно её модули и разделы; системные роли не редактируются; роль с сотрудниками
// не удаляется; axe; скриншоты матрицы 1440/1280/390.
const WIDTHS = [1440, 1280, 390] as const;
const PANEL = "#pf-context-panel";
const MIXED = "Менеджер и бухгалтер";

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

async function openRoles(page: Page): Promise<void> {
  await spaGoto(page, "/admin/roles");
  await expect(page.getByRole("heading", { level: 1, name: "Ролевая матрица" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Администратор/ })).toBeVisible();
}

function matrix(page: Page) {
  return page.locator("table.pf-matrix");
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe("Ролевая матрица: роли — данные", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; ширины проверяет блок axe");

  test("админ создаёт «Менеджер и бухгалтер», выдаёт сотруднику — тот видит ровно эти модули и разделы", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openRoles(page);

    // Системные роли — только чтение: замок, подпись, ни одного поля выбора в их столбце.
    await page.getByRole("button", { name: /^Директор.*системная роль/ }).click();
    const panel = page.locator(PANEL);
    await expect(panel.getByText(/изменить или удалить её нельзя/)).toBeVisible();
    await expect(matrix(page).getByRole("combobox")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Сохранить роль" })).toHaveCount(0);

    // Создать роль с нуля: столбец новой роли — поля выбора уровня и флажки полей.
    await page.getByRole("button", { name: "Создать роль" }).click();
    await expect(panel.getByRole("heading", { level: 3, name: "Новая роль" })).toBeVisible();
    await panel.getByLabel("Название").fill(MIXED);
    const leads = matrix(page).getByRole("combobox", {
      name: `Все сообщения, Все лиды, Каналы связи, База знаний — роль «${MIXED}»`,
    });
    await leads.selectOption({ label: "Полный доступ" });
    const payments = matrix(page).getByRole("combobox", {
      name: `Счета и оплаты · подтвердить оплату, запросить платёжку — роль «${MIXED}»`,
    });
    await payments.selectOption({ label: "Полный доступ" });
    const consequence = panel.getByRole("group", { name: "Что произойдёт" });
    await expect(consequence.getByText("Роль открывает модули: CRM, EDS.")).toBeVisible();
    await settledScreenshot(page, "roles-new");
    await panel.getByRole("button", { name: "Создать роль" }).click();
    await expect(page.getByText(`Роль «${MIXED}» создана`)).toBeVisible();
    await expect(page.getByRole("button", { name: MIXED, exact: true })).toBeVisible();
    // Выбрана созданная роль: в её столбце — поля выбора, в окне — «Сохранить роль».
    await expect(panel.getByRole("heading", { level: 3, name: MIXED })).toBeVisible();
    await expect(leads).toBeVisible();

    // Выдать роль сотруднику в Оргструктуре.
    await spaGoto(page, "/admin/org");
    await page.getByRole("link", { name: "Открыть карточку: Демо Инженеров" }).click();
    await expect(panel.getByRole("heading", { level: 3, name: "Демо Инженеров" })).toBeVisible();
    await panel.getByRole("checkbox", { name: /^Гл\. инженер/ }).uncheck();
    await panel.getByRole("checkbox", { name: new RegExp(`^${MIXED}`) }).check();
    await expect(panel.getByText("Сотрудник увидит модули: CRM, EDS.")).toBeVisible();
    await panel.getByRole("button", { name: "Сохранить роли" }).click();
    await expect(page.getByText("Сохранено")).toBeVisible();
    await expect(page.getByRole("row", { name: /Демо Инженеров/ })).toContainText(MIXED);

    // Сотрудник входит: рейл и подменю — ровно разделы роли, Dashboard нет — первый раздел роли.
    await signOut(page);
    await login(page, "engineer@demo.example");
    await expect(page).toHaveURL(/\/crm\/messages$/);
    await expect(railLinks(page)).toHaveText(["CRM", "EDS"]);
    const submenu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(submenu.getByRole("link")).toHaveText([
      /Все сообщения/,
      /Все лиды/,
      /Каналы связи/,
      /База знаний/,
    ]);
    await settledScreenshot(page, "roles-employee-view");
    await railLinks(page).filter({ hasText: "EDS" }).click();
    await expect(submenu.getByRole("link")).toHaveText([/Все документы/, /Счета и оплаты/]);
    // Название роли под аватаром — из данных.
    await expect(
      page.getByRole("button", { name: new RegExp(`${MIXED}: профиль и настройки`) }),
    ).toBeVisible();
    // Чужие разделы по прямому адресу — «Нет доступа».
    for (const path of ["/dashboard/queue", "/crm/clients", "/eds/inbox", "/admin/roles"]) {
      await spaGoto(page, path);
      await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    }
    await settledScreenshot(page, "roles-employee-forbidden");

    // Роль с сотрудником удалить нельзя: понятный отказ.
    await signOut(page);
    await loginAndWait(page, "admin@demo.example");
    await openRoles(page);
    await page.getByRole("button", { name: MIXED, exact: true }).click();
    await expect(
      panel.getByText(
        "Удалить нельзя: роль выдана сотрудникам (1). Сначала назначьте им другие роли в Оргструктуре.",
      ),
    ).toBeVisible();
    await expect(panel.getByRole("button", { name: "Удалить роль" })).toBeDisabled();
  });

  test("изменение роли: «Что произойдёт» — кто из сотрудников что получит и потеряет", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openRoles(page);
    await page.getByRole("button", { name: "Менеджер", exact: true }).click();
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "Менеджер" })).toBeVisible();

    const summary = matrix(page).getByRole("combobox", {
      name: "Сводка по компании — роль «Менеджер»",
    });
    await summary.selectOption({ label: "Только чтение" });
    const consequence = panel.getByRole("group", { name: "Что произойдёт" });
    await expect(
      consequence.getByText(
        /сотрудник\S* получат: Dashboard · Сводка по компании \(только чтение\)/,
      ),
    ).toBeVisible();
    await settledScreenshot(page, "roles-edit-preview");
    await panel.getByRole("button", { name: "Сохранить роль" }).click();
    await expect(page.getByText("Роль сохранена")).toBeVisible();

    // Роль из шаблона удаляется, только если её никому не выдали: у «Менеджера» сотрудники есть.
    await expect(panel.getByRole("button", { name: "Удалить роль" })).toBeDisabled();
  });

  test("свободную роль можно удалить: подтверждение и «Что произойдёт»", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openRoles(page);
    await page.getByRole("button", { name: "Создать роль" }).click();
    const panel = page.locator(PANEL);
    await panel.getByRole("radio", { name: "Снабженец" }).check();
    await panel.getByLabel("Название").fill("Склад");
    await panel.getByRole("button", { name: "Создать роль" }).click();
    await expect(page.getByRole("button", { name: "Склад", exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "Удалить роль" }).click();
    await expect(panel.getByText(/Роль исчезнет из матрицы/)).toBeVisible();
    await panel.getByRole("button", { name: "Удалить", exact: true }).click();
    await expect(page.getByText("Роль удалена")).toBeVisible();
    await expect(page.getByRole("button", { name: "Склад", exact: true })).toHaveCount(0);
  });
});

test.describe("Ролевая матрица: ширины, axe", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам тест (390 — узкий экран)");
  for (const width of WIDTHS) {
    test(`матрица на ${String(width)} px: без горизонтальной прокрутки страницы, axe 0`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await loginAndWait(page, "admin@demo.example");
      await openRoles(page);
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await expectNoViolations(page, `матрица ${String(width)}`);
      await settledScreenshot(page, "roles-matrix");

      await page.getByRole("button", { name: "Создать роль" }).click();
      await expect(
        page.locator(PANEL).getByRole("heading", { level: 3, name: "Новая роль" }),
      ).toBeVisible();
      await expectNoViolations(page, `новая роль ${String(width)}`);

      await spaGoto(page, "/admin/roles?role=2&panel=open&tab=role");
      await expect(page.locator(PANEL).getByText(/изменить или удалить её нельзя/)).toBeVisible();
      await expectNoViolations(page, `системная роль ${String(width)}`);
      await settledScreenshot(page, "roles-system");
    });
  }
});
