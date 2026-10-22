import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  railLinks,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";
import { routesFor, visibleModules } from "./support/rbac";

// Admin · Оргструктура на MSW (PLT-15): выдача ролей, «последний админ», приглашение, чтение для директора, axe, скриншоты.
const WIDTHS = [1440, 1280, 390] as const;
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

async function openOrg(page: Page): Promise<void> {
  await spaGoto(page, "/admin/org");
  await expect(page.getByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Открыть карточку: Демо Менеджеров" })).toBeVisible();
}

async function openCard(page: Page, name: string): Promise<void> {
  await page.getByRole("link", { name: `Открыть карточку: ${name}` }).click();
  await expect(page.locator(PANEL).getByRole("heading", { level: 3, name })).toBeVisible();
}

/** Скриншот высокого окна: блок «Что произойдёт» под кнопкой лежит ниже первого экрана панели. */
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

test.describe("Оргструктура: выдача ролей", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; ширины проверяет блок axe");

  test("админ выдаёт роль SUPPLY — сотрудник после входа видит только свои модули", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openOrg(page);
    await settledScreenshot(page, "org-list");

    await openCard(page, "Демо Менеджеров");
    const panel = page.locator(PANEL);
    await panel.getByRole("checkbox", { name: /^Менеджер/ }).uncheck();
    await panel.getByRole("checkbox", { name: /^Снабженец/ }).check();
    // «Что произойдёт» строится из сгенерированной матрицы, а не из текста в коде
    const modules = visibleModules("SUPPLY").join(", ");
    await expect(panel.getByText(`Сотрудник увидит модули: ${modules}.`)).toBeVisible();
    await expect(panel.getByText(/В ERP сотрудник получит доступ/)).toBeVisible();
    await tallScreenshot(page, "org-card-roles");

    await panel.getByRole("button", { name: "Сохранить роли" }).click();
    await expect(page.getByText("Сохранено")).toBeVisible();
    await expect(page.getByRole("row", { name: /Демо Менеджеров/ })).toContainText("Снабженец");
    await expect(panel.getByRole("button", { name: "Сохранить роли" })).toBeDisabled();

    // Следующий вход этого сотрудника: рейл и прямые адреса — по матрице для SUPPLY
    await signOut(page);
    await loginAndWait(page, "manager@demo.example");
    await expect(railLinks(page)).toHaveText(visibleModules("SUPPLY"));
    const { hidden, visible } = routesFor("SUPPLY");
    expect(hidden).toContain("/crm/leads");
    expect(visible).toContain("/erp/calc");
    for (const route of hidden) {
      await spaGoto(page, route);
      await expect(
        page.getByRole("heading", { level: 1, name: "Нет доступа" }),
        route,
      ).toBeVisible();
    }
    for (const route of visible) {
      await spaGoto(page, route);
      await expect(page.getByRole("heading", { level: 2 }), route).toBeVisible();
      await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" }), route).toHaveCount(
        0,
      );
    }
  });

  test("отключённый сотрудник не входит; включённый снова входит", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openOrg(page);
    await openCard(page, "Демо Бухгалтеров");
    const panel = page.locator(PANEL);

    await panel.getByRole("button", { name: "Отключить сотрудника" }).click();
    await expect(panel.getByText("Вход в Платформу, CRM и ERP закроется.")).toBeVisible();
    await tallScreenshot(page, "org-disable");
    await panel.getByRole("button", { name: "Отключить", exact: true }).click();
    await expect(panel.getByText("Сотрудник отключён и не может войти.")).toBeVisible();
    await expect(page.getByRole("row", { name: /Демо Бухгалтеров/ })).toContainText("Отключён");

    await signOut(page);
    await page.getByLabel("Электронная почта").fill("accountant@demo.example");
    await page.getByLabel("Пароль").fill("demo-pass-1");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert")).toContainText("Неверная почта или пароль");
  });
});

test.describe("Оргструктура: последний администратор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("снять у себя последнюю роль ADMIN нельзя — понятный текст и неактивная кнопка", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openOrg(page);
    const panel = page.locator(PANEL);

    // Пока есть второй администратор, роль снять можно
    await openCard(page, "Демо Универсалов");
    await panel.getByRole("checkbox", { name: /^Администратор/ }).uncheck();
    await expect(panel.getByRole("button", { name: "Сохранить роли" })).toBeEnabled();
    await panel.getByRole("button", { name: "Сохранить роли" }).click();
    await expect(page.getByText("Сохранено")).toBeVisible();

    // Остался один — сам вошедший
    await openCard(page, "Демо Админов");
    await panel.getByRole("checkbox", { name: /^Администратор/ }).uncheck();
    const note = panel.getByText(
      "Вы единственный администратор: снять роль «Администратор» нельзя. Сначала назначьте администратором другого сотрудника.",
    );
    await expect(note).toBeVisible();
    await expect(panel.getByRole("button", { name: "Сохранить роли" })).toBeDisabled();
    await expect(panel.getByRole("button", { name: "Отключить сотрудника" })).toBeDisabled();
    await tallScreenshot(page, "org-last-admin");
    await expectNoViolations(page, "last admin");

    // Вернули флажок — запрет снят, роли не менялись
    await panel.getByRole("checkbox", { name: /^Администратор/ }).check();
    await expect(note).toHaveCount(0);
  });
});

test.describe("Оргструктура: приглашение", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("пригласить по почте: проверка полей, блок «Что произойдёт», новый сотрудник в списке", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openOrg(page);
    // Главная кнопка модуля в подменю ведёт к форме в боковом окне
    await page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: "Пригласить сотрудника" })
      .click();
    const panel = page.locator(PANEL);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
    ).toBeVisible();

    await panel.getByRole("button", { name: "Отправить приглашение" }).click();
    await expect(panel.getByText("Укажите имя и фамилию")).toBeVisible();
    await expect(panel.getByText("Укажите почту сотрудника")).toBeVisible();
    await expect(panel.getByText("Выберите хотя бы одну роль.")).toBeVisible();

    await panel.getByLabel("Имя и фамилия").fill("Тест Приглашённый");
    await panel.getByLabel("Электронная почта").fill("invitee@demo.example");
    await panel.getByLabel("Должность (необязательно)").fill("Бухгалтер-кассир");
    await panel.getByRole("checkbox", { name: /^Бухгалтер/ }).check();
    await expect(
      panel.getByText("На указанную почту уйдёт письмо с временным паролем"),
    ).toBeVisible();
    await tallScreenshot(page, "org-invite");
    await panel.getByRole("button", { name: "Отправить приглашение" }).click();

    await expect(panel.getByRole("heading", { level: 3, name: "Тест Приглашённый" })).toBeVisible();
    const row = page.getByRole("row", { name: /Тест Приглашённый/ });
    await expect(row).toContainText("Приглашён");
    await expect(row).toContainText("Бухгалтер-кассир");
    await expect(row).toContainText("Бухгалтер");
  });

  test("почта уже есть — ошибка у поля; почта не подключена — сотрудник создан, письмо не ушло", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const panel = page.locator(PANEL);
    await panel.getByLabel("Имя и фамилия").fill("Дубль Почты");
    await panel.getByLabel("Электронная почта").fill("manager@demo.example");
    await panel.getByRole("checkbox", { name: /^Менеджер/ }).check();
    await panel.getByRole("button", { name: "Отправить приглашение" }).click();
    await expect(panel.getByText("Сотрудник с такой почтой уже есть.")).toBeVisible();

    await panel.getByLabel("Электронная почта").fill("nomail@demo.example");
    await panel.getByRole("button", { name: "Отправить приглашение" }).click();
    await expect(panel.getByRole("alert")).toContainText("письмо не отправлено");
    await panel.getByRole("button", { name: "Открыть карточку" }).click();
    await expect(panel.getByRole("heading", { level: 3, name: "Дубль Почты" })).toBeVisible();
  });
});

test.describe("Оргструктура: директор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе");

  test("директор читает список и карточки, роли и приглашение недоступны", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openOrg(page);
    await expect(page.getByRole("button", { name: "Пригласить сотрудника" })).toHaveCount(0);
    await openCard(page, "Демо Менеджеров");
    const panel = page.locator(PANEL);
    await expect(
      panel.getByText("Только просмотр: роли и доступ меняет администратор."),
    ).toBeVisible();
    await expect(panel.getByRole("checkbox")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Сохранить роли" })).toHaveCount(0);
    await settledScreenshot(page, "org-readonly");
    await expectNoViolations(page, "readonly");
  });

  test("сотрудник без раздела Admin получает «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    await page.goto("/admin/org");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });
});

test.describe("Оргструктура: axe и скриншоты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`список с карточкой сотрудника на ${String(width)}: axe без нарушений`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await openOrg(page);
      await expectNoViolations(page, `list ${String(width)}`);
      await settledScreenshot(page, "org-list");

      await openCard(page, "Демо Менеджеров");
      await expectNoViolations(page, `card ${String(width)}`);
      await settledScreenshot(page, "org-card");

      await spaGoto(page, "/admin/org?invite=open&panel=open");
      await expect(
        page.locator(PANEL).getByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
      ).toBeVisible();
      await expectNoViolations(page, `invite ${String(width)}`);
      await settledScreenshot(page, "org-invite-form");
    });
  }

  test("пустой поиск и нет сотрудника в адресе: тексты словами, axe без нарушений", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "admin@demo.example");
    await openOrg(page);
    await page.getByRole("searchbox", { name: "Поиск по сотрудникам" }).fill("несуществующий");
    await expect(page.getByRole("heading", { level: 2, name: "Никого не найдено" })).toBeVisible();
    await settledScreenshot(page, "org-no-match");
    await expectNoViolations(page, "no match");
    await page.getByRole("button", { name: "Сбросить фильтры" }).click();
    await expect(
      page.getByRole("link", { name: "Открыть карточку: Демо Менеджеров" }),
    ).toBeVisible();

    await spaGoto(page, "/admin/org?employee=u-missing&panel=open");
    await expect(
      page.locator(PANEL).getByRole("heading", { level: 3, name: "Сотрудник не найден" }),
    ).toBeVisible();
  });
});
