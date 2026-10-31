import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot as shot, spaGoto, waitForMotionEnd } from "./support/app";
import { pickFiles } from "./support/fields";

// EDS · «Проекты: договор, акт, сканы» на MSW (D2-5): бухгалтер ведёт проект ПР-2026-104 от «Сформировать проект договора» до
// «Подписан (скан)», акт проекта ПР-2026-097 — до «Выполнено»; менеджер читает без кнопок; администратор не видит раздел;
// в интерфейсе нет слова «счёт-фактура»; axe (WCAG 2.1 AA); на 390 px договор и акт — листы на весь экран (@mobile).
const PANEL = "#pf-context-panel";
const PR = (n: number) =>
  `/eds/projects/${encodeURIComponent(`ПР-2026-${String(n).padStart(3, "0")}`)}`;

// Скан — вымышленный: сигнатура PDF и несколько байт, без персональных данных.
const SCAN = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% demo scan, fictional\n%%EOF\n"),
});

/** Снимок без всплывающих сообщений antd: они держатся несколько секунд и закрывают шапку. */
async function settledScreenshot(page: Page, name: string): Promise<void> {
  await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 15_000 });
  await shot(page, name);
}

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

async function expectNoInvoiceWord(page: Page): Promise<void> {
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/фактур/i);
}

async function openProject(page: Page, n: number, tab?: "contract" | "act"): Promise<void> {
  await spaGoto(page, `${PR(n)}${tab ? `?panel=open&tab=${tab}` : ""}`);
  await expect(
    page.getByRole("heading", { level: 1, name: `Проект ПР-2026-${String(n).padStart(3, "0")}` }),
  ).toBeVisible();
}

test.describe("Проекты: бухгалтер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — блок @mobile");

  test("список → договор от проекта до «Подписан (скан)» → акт → «Выполнено»", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/projects");
    await expect(page.getByRole("heading", { level: 1, name: /Проекты/ })).toBeVisible();
    const table = page.getByRole("table");
    await expect(table.getByText("ПР-2026-104")).toBeVisible();
    await expect(table.getByText("ПР-2026-097")).toBeVisible();
    await settledScreenshot(page, "projects-list");
    await expectNoViolations(page, "список проектов");
    await expectNoInvoiceWord(page);

    // фильтр «С проблемами»: проект без договора
    await page.getByRole("checkbox", { name: "С проблемами" }).click();
    await expect(table.getByText("ПР-2026-097")).toHaveCount(0);
    await expect(table.getByText("ПР-2026-104")).toBeVisible();
    await page.getByRole("checkbox", { name: "С проблемами" }).click();
    await expect(table.getByText("ПР-2026-097")).toBeVisible();

    // карточка проекта без договора: «Сформировать проект договора» из принятого КП
    await openProject(page, 104, "contract");
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await settledScreenshot(page, "contract-none");
    await expectNoViolations(page, "договор: нет проекта");
    await panel.getByRole("button", { name: "Сформировать проект договора" }).click();

    await expect(panel.getByText("Проект ещё не отправлен клиенту.")).toBeVisible();
    await panel.getByRole("button", { name: "На согласование клиенту" }).click();
    await expect(panel.getByText("Проект у клиента на согласовании редакции.")).toBeVisible();
    await panel.getByRole("button", { name: "Отметить: согласован клиентом" }).click();
    await panel.getByRole("button", { name: "Отметить: выставлен у оператора" }).click();
    await expect(
      panel.getByText(/Договор выставлен у оператора\. Когда обе стороны/),
    ).toBeVisible();
    await settledScreenshot(page, "contract-issued");
    await expectNoViolations(page, "договор: выставлен у оператора");

    // скан: файл не выбран — кнопка неактивна; чужой тип не принимается; PDF — «Подписан (скан)»
    const submit = panel.getByRole("button", { name: "Прикрепить скан → Подписан" });
    await expect(submit).toBeDisabled();
    const input = panel.getByLabel("Скан подписанного договора");
    await input.setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("not a scan"),
    });
    await expect(submit).toBeDisabled();
    await expect(panel.getByText(/Нужен PDF или изображение/)).toBeVisible();
    await input.setInputFiles(SCAN("dogovor-demo.pdf"));
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(
      panel.getByText("Договор подписан обеими сторонами, скан сохранён."),
    ).toBeVisible();
    await expect(panel.getByText("Подписан (скан)").first()).toBeVisible();
    await settledScreenshot(page, "contract-signed");
    await expectNoViolations(page, "договор подписан");
    await expectNoInvoiceWord(page);

    // акт: проект 097, скан подписанного акта → проект «Выполнено»
    await openProject(page, 97, "act");
    const act = page.locator(PANEL);
    await expect(act.getByText(/Акт у клиента на приёмке/)).toBeVisible();
    await settledScreenshot(page, "act-issued");
    await pickFiles(act.getByLabel("Скан подписанного акта"), SCAN("akt-demo.pdf"));
    await act.getByRole("button", { name: "Прикрепить скан → Подписан" }).click();
    await expect(act.getByText("Акт подписан, скан сохранён.")).toBeVisible();
    await expect(
      page.getByText("Проект выполнен: акт подписан, все счета оплачены."),
    ).toBeVisible();
    await settledScreenshot(page, "project-done");
    await expectNoViolations(page, "проект выполнен");
    await expectNoInvoiceWord(page);
  });

  test("реестр «Все документы»: договор и акт проекта — вкладки и ссылка «В проекте»", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/documents");
    await expect(page.getByRole("heading", { level: 1, name: "Все документы" })).toBeVisible();
    await page.getByRole("tab", { name: "Договоры" }).click();
    const link = page.getByRole("link", {
      name: /Открыть в проекте: Поставка стрелочных переводов/,
    });
    await expect(link).toBeVisible();
    await settledScreenshot(page, "registry-contracts");
    await expectNoViolations(page, "реестр: договоры");
    await link.click();
    await expect(page.getByRole("heading", { level: 1, name: "Проект ПР-2026-105" })).toBeVisible();
  });
});

test.describe("Проекты: чтение и доступ", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  test("менеджер читает карточку, действий нет", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openProject(page, 105, "contract");
    await expect(page.getByText("Только чтение", { exact: true })).toBeVisible();
    await expect(
      page.locator(PANEL).getByRole("button", { name: /Отметить: согласован клиентом/ }),
    ).toHaveCount(0);
    await expectNoViolations(page, "менеджер: чтение");
  });

  test("администратор без раздела eds.projects: «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/eds/projects");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    await spaGoto(page, PR(104));
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    await expectNoViolations(page, "администратор: нет доступа");
  });
});

// @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом.
test.describe("Проекты: телефон", () => {
  test(
    "список — карточки; договор и акт — листы на весь экран",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      test.skip(!isMobile, "узкий экран — проект mobile");
      await loginAndWait(page, "accountant@demo.example");
      await spaGoto(page, "/eds/projects");
      await expect(page.getByRole("heading", { level: 1, name: /Проекты/ })).toBeVisible();
      await settledScreenshot(page, "mobile-projects-list");
      await expectNoViolations(page, "мобильный список проектов");

      await spaGoto(page, `${PR(105)}?sheet=contract`);
      const sheet = page.getByRole("dialog");
      await expect(sheet.getByRole("heading", { name: "Договор ДОГ-2026/105" })).toBeVisible();
      const box = await sheet.boundingBox();
      const viewport = page.viewportSize();
      expect(box?.width).toBe(viewport?.width);
      await settledScreenshot(page, "mobile-contract-sheet");
      await expectNoViolations(page, "мобильный лист договора");
      await expectNoInvoiceWord(page);
    },
  );
});
