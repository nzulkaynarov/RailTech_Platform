import { type Locator, type Page, expect, test } from "@playwright/test";

import { login, loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ДВ-4б: второй фактор обязателен держателям разделов с деньгами и доступом — настройка сразу после пароля, свежий код
// перед подтверждением реквизитов и выдачей роли, сброс фактора администратором. axe 0, снимки 1440 и 390.
const WIDTHS = [1440, 390] as const;
const SHOTS = process.env["E2E_SCREENSHOT_DIR"];
const FACTOR_STATE = "rt-pf-mock-2fa";

async function shot(page: Page, name: string): Promise<void> {
  await waitForMotionEnd(page);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** Сценарии моков (`src/mocks/secondFactor.ts`) и сотрудники с включённым и запомненным фактором — до входа. */
async function scenario(
  page: Page,
  options: { required?: boolean; stepUp?: boolean; withFactor?: string[] },
): Promise<void> {
  const factors = Object.fromEntries(
    (options.withFactor ?? []).map((id) => [
      id,
      { enabled: true, enabledAt: "2026-11-23T09:00:00Z", backup: ["A"], remembered: true },
    ]),
  );
  // Строка, а не функция: у e2e нет DOM-типов. Состояние фактора не перетирается при перезагрузке страницы.
  await page.addInitScript(`(() => {
    const s = window.localStorage;
    ${options.required ? `s.setItem("rt-pf-mock-2fa-required", "1");` : ""}
    ${options.stepUp ? `s.setItem("rt-pf-mock-step-up", "1");` : ""}
    if (${String(Object.keys(factors).length > 0)} && !s.getItem(${JSON.stringify(FACTOR_STATE)})) {
      s.setItem(${JSON.stringify(FACTOR_STATE)}, ${JSON.stringify(JSON.stringify(factors))});
    }
  })()`);
}

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

for (const width of WIDTHS) {
  test.describe(`второй фактор обязателен, ${String(width)} px`, { tag: "@mobile" }, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    });

    test("вход без фактора закрыт: настройка сразу после пароля, резервные коды, затем приложение", async ({
      page,
    }) => {
      await scenario(page, { required: true });
      await login(page, "accountant@demo.example");

      await expect(
        page.getByRole("heading", { level: 1, name: "Настройте вход с кодом" }),
      ).toBeVisible();
      await expect(page.getByRole("img", { name: /QR-код/ })).toBeVisible();
      await expect(page).toHaveURL(/\/login$/);
      await shot(page, `enroll-${String(width)}`);
      await expectNoViolations(page, "настройка при входе");
      await noHorizontalScroll(page);

      await page.getByLabel("Код из приложения").fill("000000");
      await page.getByRole("button", { name: "Подтвердить" }).click();
      await expect(page.getByRole("alert")).toContainText("Неверный код");
      await expect(page).toHaveURL(/\/login$/);

      await page.getByLabel("Код из приложения").fill("123456");
      await page.getByRole("button", { name: "Подтвердить" }).click();
      await expect(page.getByText("4F7K-92QD")).toBeVisible();
      await expect(page).toHaveURL(/\/login$/);
      await shot(page, `enroll-codes-${String(width)}`);
      await expectNoViolations(page, "резервные коды");

      await page.getByRole("button", { name: "Я сохранил коды" }).click();
      await expect(page).toHaveURL(/\/dashboard\/queue$/);
    });

    test("менеджеру фактор не нужен: вход по паролю", async ({ page }) => {
      await scenario(page, { required: true });
      await loginAndWait(page, "manager@demo.example");
    });

    test("подтверждение новых реквизитов — со свежим кодом", async ({ page }) => {
      await scenario(page, { stepUp: true, withFactor: ["u-demo-accountant"] });
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/crm/clients?kind=bank_changes");
      const list = page.getByRole("list", { name: "Запросы на смену реквизитов" });
      await list.getByRole("button", { name: "Подтвердить" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Подтвердить" }).click();

      const stepUp = page.getByRole("dialog", { name: "Введите код из приложения" });
      await expect(stepUp).toBeVisible();
      await shot(page, `step-up-${String(width)}`);
      await expectNoViolations(page, "свежий код");

      await stepUp.getByLabel("Код из приложения или резервный").fill("000000");
      await stepUp.getByRole("button", { name: "Подтвердить" }).click();
      await expect(stepUp.getByRole("alert")).toContainText("Неверный код");

      await stepUp.getByLabel("Код из приложения или резервный").fill("123456");
      await stepUp.getByRole("button", { name: "Подтвердить" }).click();
      // после верного кода действие повторилось само: запрос решён
      await expect(page.getByText("Запросов на проверке нет")).toBeVisible();
    });

    test("выдача роли — со свежим кодом; сброс фактора с причиной", async ({ page }) => {
      await scenario(page, { stepUp: true, withFactor: ["u-demo-admin"] });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org?view=list");
      await page.getByRole("link", { name: "Открыть карточку: Демо Менеджеров" }).click();
      const panel: Locator = page.locator("#pf-context-panel, .pf-crm-sheet").last();
      await expect(panel.getByRole("heading", { level: 3, name: "Демо Менеджеров" })).toBeVisible();

      await panel.getByRole("checkbox", { name: /^Снабженец/ }).check();
      await panel.getByRole("button", { name: "Сохранить роли" }).click();
      const stepUp = page.getByRole("dialog", { name: "Введите код из приложения" });
      await expect(stepUp).toBeVisible();
      await stepUp.getByLabel("Код из приложения или резервный").fill("123456");
      await stepUp.getByRole("button", { name: "Подтвердить" }).click();
      await expect(page.getByText("Сохранено")).toBeVisible();

      await panel.getByRole("button", { name: "Сбросить второй фактор" }).click();
      await expect(panel.getByRole("group", { name: "Сброс второго фактора" })).toBeVisible();
      await shot(page, `reset-factor-${String(width)}`);
      await expectNoViolations(page, "сброс фактора");
      const confirm = panel.getByRole("button", { name: "Сбросить", exact: true });
      await expect(confirm).toBeDisabled();
      await panel.getByLabel("Причина").fill("Потерян телефон, подтверждено звонком");
      await confirm.click();
      await expect(page.getByText(/Второй фактор сброшен/)).toBeVisible();
    });
  });
}
