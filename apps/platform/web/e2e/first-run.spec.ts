import { randomUUID } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { openAvatarMenu, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Первый запуск в Платформе на MSW (W13-A4): экран до входа, администратор, своя компания, баннер и мастер из пяти шагов,
// сотрудник без почты с одноразовым временным паролем. Код и пароли — случайные на каждый прогон.
const PANEL = "#pf-context-panel";
const SETUP_KEY = "rt-pf-mock-setup";
const WIDTHS = [1440, 390] as const;

const secret = (prefix: string) => `${prefix}-${randomUUID().replaceAll("-", "").slice(0, 12)}`;

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

/** Состояние мока до загрузки страницы: записывается один раз, перезагрузка его не затирает. */
async function seedSetup(page: Page, state: Record<string, unknown>): Promise<void> {
  const key = JSON.stringify(SETUP_KEY);
  const value = JSON.stringify(JSON.stringify(state));
  await page.addInitScript(
    `if (!window.localStorage.getItem(${key})) window.localStorage.setItem(${key}, ${value});`,
  );
}

const FRESH = { needsAdmin: false, code: "", fresh: true, companyCreated: false, done: {} };

async function freshInstall(page: Page, code: string): Promise<void> {
  await seedSetup(page, { ...FRESH, needsAdmin: true, code });
}

async function createAdmin(page: Page, code: string, password: string): Promise<void> {
  await page.getByLabel("Код первого запуска").fill(code);
  await page.getByLabel("Имя и фамилия").fill("Первая Админова");
  await page.getByLabel("Электронная почта администратора").fill("first.admin@demo.example");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByLabel("Повторите пароль").fill(password);
  await page.getByRole("button", { name: "Создать администратора и войти" }).click();
  await expect(page).toHaveURL(/\/admin\/setup$/);
  await expect(page.getByRole("heading", { level: 2, name: "Ваша компания" })).toBeVisible();
}

/** Сообщение antd живёт несколько секунд: снимок ждёт, пока оно исчезнет, чтобы оно не закрывало шапку. */
async function toastsGone(page: Page): Promise<void> {
  await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
}

async function createCompany(page: Page): Promise<void> {
  await page.getByLabel("Название компании").fill("ООО Демо Рельс");
  await page.getByLabel("ИНН (необязательно)").fill("123456789");
  await page.getByRole("button", { name: "Создать компанию" }).click();
  await expect(page.getByText("Своя компания создана.")).toBeVisible();
}

async function inviteWithoutMail(page: Page, email: string): Promise<string> {
  await spaGoto(page, "/admin/org?invite=open&panel=open");
  const panel = page.locator(PANEL);
  await expect(
    panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
  ).toBeVisible();
  await panel.getByRole("radio", { name: "Временным паролем, без почты" }).check();
  await panel.getByLabel("Имя и фамилия").fill("Тест Без Почты");
  await panel.getByLabel("Электронная почта").fill(email);
  await panel.getByRole("checkbox", { name: /^Снабженец/ }).check();
  await expect(panel.getByText(/Вы увидите временный пароль один раз/)).toBeVisible();
  await panel.getByRole("button", { name: "Создать и показать пароль" }).click();
  const field = panel.getByLabel("Временный пароль", { exact: true });
  await expect(field).toBeVisible();
  return field.inputValue();
}

test.describe("Первый запуск: полный путь", () => {
  test.skip(({ isMobile }) => isMobile, "сценарий на десктопе; ширины проверяет блок axe");

  test("код -> администратор -> компания -> баннер и пять шагов -> сотрудник без почты -> вход и смена пароля", async ({
    page,
    context,
    baseURL,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL });
    const code = secret("code");
    const adminPassword = secret("adm");
    await freshInstall(page, code);

    // Вход ведёт на «Первый запуск»; неверный код — слова, форма остаётся
    await page.goto("/login");
    await expect(page).toHaveURL(/\/setup$/);
    await expect(page.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
    await expect(page.getByText("Что произойдёт")).toBeVisible();
    await page.getByLabel("Код первого запуска").fill("wrong-code");
    await page.getByLabel("Имя и фамилия").fill("Первая Админова");
    await page.getByLabel("Электронная почта администратора").fill("first.admin@demo.example");
    await page.getByLabel("Пароль", { exact: true }).fill(adminPassword);
    await page.getByLabel("Повторите пароль").fill(adminPassword);
    await page.getByRole("button", { name: "Создать администратора и войти" }).click();
    await expect(page.getByRole("alert")).toContainText("Код неверный");

    // Верный код: администратор создан, сессия открыта, мастер
    await createAdmin(page, code, adminPassword);
    await expect(page.getByText("Администратор создан: Первая Админова.")).toBeVisible();

    // Своя компания: ошибка поля от ERP, затем создание
    await page.getByLabel("Название компании").fill("ООО Демо Рельс");
    await page.getByLabel("ИНН (необязательно)").fill("000");
    await page.getByRole("button", { name: "Создать компанию" }).click();
    await expect(page.getByText("Компания с таким ИНН уже есть.")).toBeVisible();
    await createCompany(page);

    // Пять шагов; каждый ведёт на свой экран
    const steps = page.getByRole("list", { name: "Шаги настройки" });
    await expect(steps.getByRole("listitem")).toHaveCount(5);
    await expect(page.getByText("Готово 0 из 5")).toBeVisible();
    await steps.getByRole("link", { name: "Подключить бота" }).click();
    await expect(page).toHaveURL(/\/admin\/integrations\?card=telegram/);
    await expect(page.getByRole("heading", { level: 1, name: "Внешние интеграции" })).toBeVisible();

    // Баннер на других экранах Платформы
    await spaGoto(page, "/admin/org");
    const banner = page.getByRole("region", { name: "Настройка Платформы" });
    await expect(banner).toContainText("Настройка Платформы: готово 0 из 5");
    await banner.getByRole("link", { name: "Продолжить настройку" }).click();
    await expect(page).toHaveURL(/\/admin\/setup$/);
    await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);

    // Сотрудник без почты: пароль показан один раз, копируется, после «Готово» исчезает
    const email = "no.mail@demo.example";
    const temporary = await inviteWithoutMail(page, email);
    const panel = page.locator(PANEL);
    await expect(panel.getByText(/Пароль показан один раз/)).toBeVisible();
    await panel.getByRole("button", { name: "Копировать" }).click();
    await expect(panel.getByText("Пароль скопирован")).toBeVisible();
    expect(await page.evaluate<string>("navigator.clipboard.readText()")).toBe(temporary);
    await panel.getByRole("button", { name: "Готово: пароль передан" }).click();
    await expect(panel.getByRole("heading", { level: 3, name: "Тест Без Почты" })).toBeVisible();
    await expect(page.getByLabel("Временный пароль", { exact: true })).toHaveCount(0);
    await expect(page.getByText(temporary)).toHaveCount(0);
    expect(page.url()).not.toContain(temporary);
    await expect(page.getByRole("row", { name: /Тест Без Почты/ })).toContainText("Приглашён");

    // Шаг «Первый сотрудник» теперь сделан
    await spaGoto(page, "/admin/setup");
    await expect(page.getByText("Готово 1 из 5")).toBeVisible();
    await expect(
      steps.getByRole("listitem").filter({ hasText: "Первый сотрудник" }).getByText("Готово"),
    ).toBeVisible();

    // Сотрудник входит с временным паролем и обязан его сменить
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Электронная почта").fill(email);
    await page.getByLabel("Пароль").fill("не-тот-пароль");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert")).toContainText("Неверная почта или пароль");
    await page.getByLabel("Пароль").fill(temporary);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/change-password$/);
    const own = secret("own");
    await page.getByLabel("Текущий пароль").fill(temporary);
    await page.getByLabel("Новый пароль", { exact: true }).fill(own);
    await page.getByLabel("Повторите новый пароль").fill(own);
    await page.getByRole("button", { name: "Сменить пароль" }).click();
    await expect(page).not.toHaveURL(/\/change-password$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Баннер настройки — только администратору
    await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
  });

  test("«Скрыть» запоминается; когда всё сделано, баннера нет, а мастер говорит об этом словами", async ({
    page,
  }) => {
    await seedSetup(page, FRESH);
    await page.goto("/login");
    await page.getByLabel("Электронная почта").fill("admin@demo.example");
    await page.getByLabel("Пароль").fill(secret("pw"));
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await spaGoto(page, "/admin/org");
    const banner = page.getByRole("region", { name: "Настройка Платформы" });
    await expect(banner).toBeVisible();

    await banner.getByRole("button", { name: "Скрыть баннер настройки" }).click();
    await expect(banner).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    await expect(banner).toHaveCount(0);

    // Мастер остаётся по адресу; все шаги сделаны -> «Всё готово»
    const done = JSON.stringify({
      needsAdmin: false,
      code: "",
      fresh: true,
      companyCreated: true,
      done: { bot: true, erp: true, mail: true, models: true, first_employee: true },
    });
    await page.evaluate(
      `window.localStorage.setItem(${JSON.stringify(SETUP_KEY)}, ${JSON.stringify(done)});
       window.localStorage.removeItem("rt-pf-setup-banner-hidden:u-demo-admin");`,
    );
    await page.reload();
    await spaGoto(page, "/admin/setup");
    await expect(page.getByText("Всё готово: Платформа настроена.")).toBeVisible();
    await expect(page.getByText("Готово 5 из 5")).toBeVisible();
    await spaGoto(page, "/admin/org");
    await expect(page.getByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
  });

  test("директор баннера не видит, менеджер на мастере — «Нет доступа»", async ({ page }) => {
    await seedSetup(page, FRESH);
    await page.goto("/login");
    await page.getByLabel("Электронная почта").fill("director@demo.example");
    await page.getByLabel("Пароль").fill(secret("pw"));
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
    await spaGoto(page, "/admin/org");
    await expect(page.getByRole("heading", { level: 1, name: "Оргструктура" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Настройка Платформы" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Пригласить сотрудника" })).toHaveCount(0);

    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await page.getByLabel("Электронная почта").fill("manager@demo.example");
    await page.getByLabel("Пароль").fill(secret("pw"));
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).not.toHaveURL(/\/login/);
    await spaGoto(page, "/admin/setup");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
  });
});

test.describe("Первый запуск: axe и скриншоты", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`экраны первого запуска на ${String(width)}: axe без нарушений`, async ({
      page,
      context,
      baseURL,
    }) => {
      await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      const code = secret("code");
      const password = secret("adm");
      await freshInstall(page, code);

      await page.goto("/setup");
      await expect(page.getByRole("heading", { level: 1, name: "Первый запуск" })).toBeVisible();
      await expectNoViolations(page, `setup ${String(width)}`);
      await settledScreenshot(page, "first-run-setup");

      await createAdmin(page, code, password);
      await expectNoViolations(page, `wizard ${String(width)}`);
      await settledScreenshot(page, "first-run-wizard");

      await createCompany(page);
      await toastsGone(page);
      await expectNoViolations(page, `wizard company ${String(width)}`);
      await settledScreenshot(page, "first-run-wizard-steps");

      await spaGoto(page, "/admin/org");
      await expect(page.getByRole("region", { name: "Настройка Платформы" })).toBeVisible();
      await expectNoViolations(page, `banner ${String(width)}`);
      await settledScreenshot(page, "first-run-banner");

      await inviteWithoutMail(page, "no.mail@demo.example");
      await expectNoViolations(page, `password ${String(width)}`);
      await settledScreenshot(page, "first-run-password");
      await page.locator(PANEL).getByRole("button", { name: "Готово: пароль передан" }).click();
      await expect(
        page.locator(PANEL).getByRole("heading", { level: 3, name: "Тест Без Почты" }),
      ).toBeVisible();

      await page.locator(PANEL).getByRole("button", { name: "Выдать временный пароль" }).click();
      await expect(
        page.locator(PANEL).getByRole("group", { name: "Выдать временный пароль" }),
      ).toBeVisible();
      await expectNoViolations(page, `issue ${String(width)}`);
      await settledScreenshot(page, "first-run-issue-confirm");
    });
  }

  test("«Первый запуск» уже выполнен: экран отправляет ко входу", async ({ page }) => {
    await page.goto("/setup");
    await expect(
      page.getByRole("heading", { level: 1, name: "Первый запуск уже выполнен" }),
    ).toBeVisible();
    await expectNoViolations(page, "setup done");
    await page.getByRole("link", { name: "К входу" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});
