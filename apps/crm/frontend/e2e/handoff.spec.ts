import { expect, test } from "@playwright/test";

// Сценарий C2–C3 (BUSINESS.md): менеджер видит эскалацию, забирает лида и отвечает.
// Данные: `python -m app seed-demo` (лид «Азиз» в handoff с горячей эскалацией).
const email = process.env["E2E_MANAGER_EMAIL"] ?? "manager@demo.local";
const password = process.env["E2E_MANAGER_PASSWORD"] ?? "";

test("login → inbox → lead card → take → reply", async ({ page }) => {
  test.skip(!password, "E2E_MANAGER_PASSWORD не задан");
  await page.goto("/");
  await page.waitForURL(/\/login/);
  await expect(page.getByText("Вход в CRM")).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();

  await expect(page.getByText("Эскалации").first()).toBeVisible();
  const item = page.locator(".ant-list-item", { hasText: "Интеграция 3 касс АТОЛ с 1С" }).first();
  await item.getByRole("link", { name: /Азиз/ }).click();
  // Десктоп — колонка «Почему система так решила», телефон — вкладка «Почему».
  await expect(
    page.getByText("Почему система так решила").or(page.getByRole("tab", { name: "Почему" })),
  ).toBeVisible();
  await expect(page.getByText("Ок, пусть позвонят, лучше после 15:00")).toBeVisible();

  const take = page.getByRole("button", { name: "Забрать" });
  const reply = page.getByPlaceholder("Ответ лиду…");
  await expect(take.or(reply)).toBeVisible();
  if (await take.isVisible()) await take.click();
  await expect(reply).toBeVisible();
  const text = `Здравствуйте! Подготовлю расчёт сегодня (${String(Date.now())})`;
  await reply.fill(text);
  await page.getByRole("button", { name: "Отправить" }).click();
  await expect(page.getByTestId("chat-thread").getByText(text)).toBeVisible();
  await page.screenshot({
    path: `test-results/lead-${test.info().project.name}.png`,
    fullPage: true,
  });
});
