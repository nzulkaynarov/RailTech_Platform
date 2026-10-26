import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Хвосты QA ролей (волна 11b, T1 R-1c) на MSW: R3-D-1 — хотя бы одна роль (интерфейс и 422 ROLES_REQUIRED), R3-D-3 —
// число и глагол в «Что произойдёт», R3-D-4 — боковое окно не теряет несохранённое при смене ширины, ссылка директора
// во вкладке «Сотрудники» ведёт в карточку для чтения. axe и скриншоты на 1440 и 390 px.
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

async function resize(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await waitForMotionEnd(page);
}

function matrix(page: Page) {
  return page.locator("table.pf-matrix");
}

async function openRole(page: Page, role: string): Promise<void> {
  await spaGoto(page, "/admin/roles");
  await expect(page.getByRole("heading", { level: 1, name: "Ролевая матрица" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`^${role}`) }).click();
}

test.describe("Роли: хвосты QA (R3-D-1, R3-D-3, R3-D-4)", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`без ролей сохранить нельзя: текст и 422 ROLES_REQUIRED (${String(width)})`, async ({
      page,
    }) => {
      await resize(page, width);
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/org?employee=u-demo-manager&panel=open");
      const panel = page.locator(PANEL);
      await expect(panel.getByRole("heading", { level: 3, name: "Демо Менеджеров" })).toBeVisible();

      await panel.getByRole("checkbox", { name: /^Менеджер/ }).uncheck();
      await expect(panel.getByText(/Выберите хотя бы одну роль/)).toBeVisible();
      await expect(panel.getByRole("button", { name: "Сохранить роли" })).toBeDisabled();
      await expectNoViolations(page, `no roles ${String(width)}`);
      // В кадре — текст запрета и неактивная кнопка (на 390 они ниже первого экрана панели).
      await panel.getByRole("button", { name: "Сохранить роли" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "org-card-no-roles");

      // Прямой вызов с пустым набором (как QA R3-D-1) — 422 ROLES_REQUIRED, роли на месте.
      // Скрипт строкой, как в `spaGoto`: e2e собирается без DOM-типов, вызов идёт из страницы (через MSW).
      const refused = await page.evaluate<{ status: number; code: string }>(`(async () => {
        const csrf = /(?:^|; )rt_pf_csrf=([^;]*)/.exec(document.cookie)?.[1] ?? "";
        const response = await fetch("/api/v1/admin/users/u-demo-manager", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf) },
          body: JSON.stringify({ role_ids: [] }),
        });
        return { status: response.status, code: (await response.json()).code };
      })()`);
      expect(refused).toEqual({ status: 422, code: "ROLES_REQUIRED" });
      await page.reload();
      await expect(panel.getByRole("checkbox", { name: /^Менеджер/ })).toBeChecked();
    });
  }

  test("«Что произойдёт»: «1 сотрудник потеряет», «2 сотрудника потеряют»", async ({ page }) => {
    await resize(page, 1440);
    await loginAndWait(page, "admin@demo.example");
    const panel = page.locator(PANEL);

    await openRole(page, "Бухгалтер");
    await matrix(page)
      .getByRole("combobox", { name: "Внешний (клиент: Telegram-бот, почта) — роль «Бухгалтер»" })
      .selectOption({ label: "Скрыто" });
    await expect(panel.getByText(/^1 сотрудник потеряет: /)).toBeVisible();
    await settledScreenshot(page, "roles-preview-one");

    await openRole(page, "Гл. инженер");
    await matrix(page)
      .getByRole("combobox", { name: /^Расчёт · виза по услугам — роль «Гл\. инженер»/ })
      .selectOption({ label: "Скрыто" });
    await expect(panel.getByText(/^2 сотрудника потеряют: /)).toBeVisible();
    await expectNoViolations(page, "preview");
    await settledScreenshot(page, "roles-preview-two");
  });

  test("форма приглашения переживает 1440 → 390 → 1440", async ({ page }) => {
    await resize(page, 1440);
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/org?invite=open&panel=open");
    const panel = page.locator(PANEL);
    await expect(
      panel.getByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
    ).toBeVisible();
    await panel.getByLabel("Имя и фамилия").fill("Демо Новый");
    await panel.getByLabel("Электронная почта").fill("new@demo.example");
    await panel.getByRole("checkbox", { name: /^Бухгалтер/ }).check();

    for (const width of [390, 1440]) {
      await resize(page, width);
      await expect(panel.getByLabel("Имя и фамилия")).toHaveValue("Демо Новый");
      await expect(panel.getByLabel("Электронная почта")).toHaveValue("new@demo.example");
      await expect(panel.getByRole("checkbox", { name: /^Бухгалтер/ })).toBeChecked();
      await expectNoViolations(page, `invite ${String(width)}`);
      await settledScreenshot(page, "org-invite-kept");
    }
  });

  test("подтверждение удаления роли переживает 1440 → 390 → 1440", async ({ page }) => {
    await resize(page, 1440);
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/roles?role=new&panel=open&tab=role");
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "Новая роль" })).toBeVisible();
    await panel.getByLabel("Название").fill("Временная");
    await matrix(page)
      .getByRole("combobox", {
        name: /^Все клиенты, Все заявки, Создать заявку — роль «Временная»/,
      })
      .selectOption({ label: "Только чтение" });
    await panel.getByRole("button", { name: "Создать роль" }).click();
    await expect(page.getByText("Роль «Временная» создана")).toBeVisible();

    await panel.getByRole("button", { name: "Удалить роль" }).click();
    const confirm = panel.getByRole("group", { name: "Удалить роль?" });
    await expect(confirm).toBeVisible();
    for (const width of [390, 1440]) {
      await resize(page, width);
      await expect(confirm).toBeVisible();
      await expect(confirm.getByRole("button", { name: "Удалить", exact: true })).toBeVisible();
      await expectNoViolations(page, `delete confirm ${String(width)}`);
      await settledScreenshot(page, "roles-delete-confirm-kept");
    }
  });

  for (const width of WIDTHS) {
    test(`директор: «Сотрудники» роли — «Открыть», карточка только для чтения (${String(width)})`, async ({
      page,
    }) => {
      await resize(page, width);
      await loginAndWait(page, "director@demo.example");
      // Роль «Гл. инженер» (id 5 в демо-данных), вкладка «Сотрудники» бокового окна.
      await spaGoto(page, "/admin/roles?role=5&panel=open&tab=employees");
      const panel = page.locator(PANEL);
      const link = panel.getByRole("link", { name: "Открыть карточку: Демо Инженеров" });
      await expect(link).toHaveText("Открыть");
      await expect(panel.getByRole("link", { name: /^Изменить роли/ })).toHaveCount(0);
      await expectNoViolations(page, `director employees ${String(width)}`);
      await settledScreenshot(page, "roles-director-employees");

      await link.click();
      await expect(panel.getByRole("heading", { level: 3, name: "Демо Инженеров" })).toBeVisible();
      await expect(panel.getByRole("button", { name: "Сохранить роли" })).toHaveCount(0);
      await expect(panel.getByRole("checkbox")).toHaveCount(0);
      await settledScreenshot(page, "org-card-director-read");
    });
  }
});
