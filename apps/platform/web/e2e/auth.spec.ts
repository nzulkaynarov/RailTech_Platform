import { expect, test } from "@playwright/test";

import {
  DEMO_PASSWORD,
  login,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
} from "./support/app";

// Вход и сессия на MSW (PLT-12): ошибки по Error.code, смена обязательного пароля, выход, возврат на тот же URL.
test.describe("вход", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии входа идут на десктопе; 390 — в a11y.spec.ts");

  test("вход → /dashboard/queue, сессия переживает перезагрузку", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await expect(page.getByRole("heading", { level: 1, name: "Мои задачи" })).toBeVisible();
    await expect(page).toHaveTitle("Мои задачи — RailTech Platform");

    await page.reload();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await expect(page.getByRole("heading", { level: 1, name: "Мои задачи" })).toBeVisible();
  });

  test("корень / ведёт в Мою очередь", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/");
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
  });

  const failures: [string, string, string][] = [
    ["неверный пароль", "director@demo.example", "Неверная почта или пароль"],
    ["отключённый сотрудник", "disabled@demo.example", "Учётная запись отключена"],
    ["нет роли Платформы", "norole@demo.example", "Вам ещё не выдана роль"],
    ["слишком много попыток", "busy@demo.example", "Слишком много попыток входа"],
    ["CRM недоступна", "down@demo.example", "Не удаётся связаться с CRM"],
  ];
  for (const [title, email, text] of failures) {
    test(`ошибка входа по Error.code: ${title}`, async ({ page }) => {
      await page.goto("/login");
      await page.getByLabel("Электронная почта").fill(email);
      await page
        .getByLabel("Пароль")
        .fill(title === "неверный пароль" ? "wrong-password" : DEMO_PASSWORD);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page.getByRole("alert")).toContainText(text);
      await expect(page).toHaveURL(/\/login$/);
      if (title === "неверный пароль") await settledScreenshot(page, "login-error");
    });
  }

  test("проверка полей формы входа", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByText("Введите электронную почту")).toBeVisible();
    await expect(page.getByText("Введите пароль")).toBeVisible();
  });

  test("обязательная смена пароля: остальные адреса ведут на смену, после смены — в очередь", async ({
    page,
  }) => {
    await login(page, "new@demo.example");
    await expect(page).toHaveURL(/\/change-password$/);
    await settledScreenshot(page, "change-password");

    await page.goto("/crm/leads");
    await expect(page).toHaveURL(/\/change-password$/);
    await expect(page.getByRole("button", { name: "Отмена" })).toHaveCount(0);

    await page.getByLabel("Текущий пароль").fill("wrong-current");
    await page.getByLabel("Новый пароль", { exact: true }).fill("new-password-1");
    await page.getByLabel("Повторите новый пароль").fill("new-password-1");
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await expect(page.getByRole("alert")).toContainText("Текущий пароль указан неверно");

    await page.getByLabel("Текущий пароль").fill(DEMO_PASSWORD);
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await expect(page.getByRole("heading", { level: 1, name: "Мои задачи" })).toBeVisible();
  });

  test("смена пароля: короткий пароль и несовпадение отклоняются на форме", async ({ page }) => {
    await login(page, "new@demo.example");
    await page.getByLabel("Текущий пароль").fill(DEMO_PASSWORD);
    await page.getByLabel("Новый пароль", { exact: true }).fill("short");
    await page.getByLabel("Повторите новый пароль").fill("other");
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await expect(page.getByText("Пароль должен быть не короче 8 символов")).toBeVisible();
    await expect(page.getByText("Пароли не совпадают")).toBeVisible();
  });

  test("выход из меню аватара, а затем возврат на тот же адрес после входа", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/crm/leads?panel=open");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/crm/leads?panel=open");
    await expect(page).toHaveURL(/\/login\?next=%2Fcrm%2Fleads%3Fpanel%3Dopen$/);
    await page.getByLabel("Электронная почта").fill("manager@demo.example");
    await page.getByLabel("Пароль").fill(DEMO_PASSWORD);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/crm\/leads\?panel=open$/);
    await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
  });

  test("истёкшая сессия 401 SESSION_EXPIRED → экран входа с возвратом на тот же адрес", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await page.goto("/eds/inbox");
    await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
    await page.evaluate("window.localStorage.removeItem('rt-pf-mock-session')");
    await page.reload();
    await expect(page).toHaveURL(/\/login\?next=%2Feds%2Finbox$/);
  });

  test("меню аватара: профиль и язык ru → uz → en, язык переживает перезагрузку", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");

    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Профиль" }).click();
    const dialog = page.getByRole("dialog", { name: "Профиль" });
    await expect(dialog).toContainText("Демо Директоров");
    await expect(dialog).toContainText("director@demo.example");
    // фокус перешёл в диалог — Escape закрывает его с клавиатуры
    await expect
      .poll(() => page.evaluate("document.activeElement?.closest('[role=dialog]') !== null"))
      .toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "O‘zbekcha" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Mening vazifalarim" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Mening vazifalarim" })).toBeVisible();

    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "English" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "My tasks" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });
});
