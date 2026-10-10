import { expect, type Page, test } from "@playwright/test";

// Сценарии C4/C6 (BUSINESS.md) в упрощённом виде: админ без разработчика меняет
// приветствие, видит базу знаний, пробелы, дашборд и аудит.
const email = process.env["E2E_ADMIN_EMAIL"] ?? "admin@demo.local";
const password = process.env["E2E_ADMIN_PASSWORD"] ?? "";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await page.waitForURL(/\/inbox/);
}

test("admin sections render and greeting can be changed", async ({ page }) => {
  test.skip(!password, "E2E_ADMIN_PASSWORD не задан");
  await login(page);

  await page.goto("/dashboard");
  await expect(page.getByText("Воронка (сейчас)")).toBeVisible();

  await page.goto("/kb");
  await expect(page.getByRole("button", { name: "Загрузить файл" })).toBeVisible();
  await expect(page.getByText("Что найдёт бот")).toBeVisible();

  await page.goto("/gaps");
  await expect(page.getByText("Открытые")).toBeVisible();

  // Настройки: разделы слева (на телефоне — список), раздел в URL (дизайн-аудит 2026-10-11).
  await page.goto("/settings?section=texts");
  await expect(page.getByRole("heading", { name: "Тексты бота" })).toBeVisible();
  const greeting = page.getByRole("main").locator("textarea").first();
  const text = `Здравствуйте! Это {company} (${String(Date.now())}).`;
  await greeting.fill(text);
  await expect(page.getByText(/Предпросмотр: Здравствуйте! Это RailTech/).first()).toBeVisible();
  await expect(page.getByText("Есть несохранённые изменения")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText(/«Тексты бота» сохранены/).first()).toBeVisible();

  await page.goto("/clients");
  await page.getByRole("button", { name: "Новый клиент" }).click();
  const clientName = `E2E Клиент ${String(Date.now())}`;
  await page.getByLabel("Название").fill(clientName);
  await page.getByRole("button", { name: "Создать клиента" }).click();
  await expect(page.getByRole("heading", { name: clientName })).toBeVisible();
  await expect(page.getByRole("button", { name: "Загрузить документ" })).toBeVisible();

  await page.goto("/audit");
  await expect(page.getByText("Изменил настройки").first()).toBeVisible();
});
