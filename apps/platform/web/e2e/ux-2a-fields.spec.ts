import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, fillDate, pickFiles } from "./support/fields";

// UX-2a «Единые поля даты, файла и выбора» на MSW: системных `input type="date|file"` и `<select>` в экранах нет — дата
// `ДД.ММ.ГГГГ` с календарём на русском, файл — кнопкой «Выбрать файл» со списком, выбор — antd Select. Четыре экрана аудита
// (создать документ, резолюция, подтверждение оплаты, фильтры журнала) на 1440 и 390, axe (WCAG 2.1 AA) — 0 нарушений;
// снимки — `E2E_SCREENSHOT_DIR=docs/screens/ux-2a`.
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

function inDays(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function shown(iso: string): string {
  return iso.split("-").reverse().join(".");
}

/** Системных полей на экране нет: ни видимого `input type=date|file`, ни `select`. */
async function expectNoNativeFields(scope: Locator | Page): Promise<void> {
  await expect(
    scope.locator('input[type="date"], input[type="datetime-local"], select'),
  ).toHaveCount(0);
  for (const input of await scope.locator('input[type="file"]').all()) {
    await expect(input).toHaveClass(/pf-sr-only/);
  }
}

async function openCalendar(field: Locator): Promise<Locator> {
  await field.click();
  const popup = field.page().locator(".ant-picker-dropdown:not(.ant-picker-dropdown-hidden)");
  await expect(popup).toBeVisible();
  return popup;
}

test.describe("UX-2a: поля даты, файла и выбора", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`создать документ: срок ДД.ММ.ГГГГ и файлы кнопкой — ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/eds/new");
      await expect(page.getByRole("heading", { level: 1, name: "Создать документ" })).toBeVisible();
      await page.getByLabel("Тема").fill("Закупка мебели для переговорной");
      await page.getByLabel("Текст").fill("Прошу согласовать закупку трёх столов.");
      await page.getByLabel("Сумма, сум").fill("3 600 000");

      const due = page.getByLabel("Нужно до");
      await expect(due).toHaveAttribute("placeholder", "ДД.ММ.ГГГГ");
      const popup = await openCalendar(due);
      // календарь на русском, дни до сегодня отключены
      await expect(popup.locator(".ant-picker-content th").first()).toHaveText(/^пн$/i);
      await settledScreenshot(page, "newdoc-calendar");
      await page.keyboard.press("Escape");
      await fillDate(due, inDays(7));
      await expect(due).toHaveValue(shown(inDays(7)));

      await expect(page.getByRole("button", { name: "Выбрать файлы" })).toBeVisible();
      await pickFiles(page.getByLabel("Вложения"), [
        {
          name: "schet-mebel.pdf",
          mimeType: "application/pdf",
          buffer: Buffer.from("%PDF-1.4 счёт"),
        },
        { name: "foto-stola.png", mimeType: "image/png", buffer: Buffer.alloc(2048) },
      ]);
      const files = page.getByRole("list", { name: "Прикреплённые файлы" });
      await expect(files.getByText("schet-mebel.pdf")).toBeVisible();
      await expect(files.getByText("2 КБ")).toBeVisible();
      await expect(files.getByRole("button", { name: "Убрать файл foto-stola.png" })).toBeVisible();
      await expectNoNativeFields(page);
      await files.scrollIntoViewIfNeeded();
      await settledScreenshot(page, "newdoc");
      await expectNoViolations(page, `создать документ, ${String(width)}`);
    });

    test(`резолюция: исполнитель из списка и срок — ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26");
      let form: Locator;
      if (width === 390) {
        await page.getByRole("button", { name: "Наложить резолюцию" }).click();
        form = page
          .getByRole("dialog", { name: /^Резолюция/ })
          .getByRole("form", { name: "Резолюция директора" });
      } else {
        form = page.locator(PANEL).getByRole("form", { name: "Резолюция директора" });
      }
      await expect(form).toBeVisible();
      await form.getByLabel("Текст резолюции").fill("Посчитать с запасом по складу.");
      const employee = form.getByLabel("Сотрудник: Снабженец");
      await employee.click();
      await expect(
        page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)"),
      ).toBeVisible();
      await settledScreenshot(page, "resolution-select");
      await page.keyboard.press("Escape");
      await chooseOption(employee, "Демо Снабженцев · Специалист по снабжению");
      await fillDate(form.getByLabel("Срок расчёта"), inDays(5));
      await expectNoNativeFields(form);
      await settledScreenshot(page, "resolution");
      await expectNoViolations(page, `резолюция, ${String(width)}`);
    });

    test(`подтверждение оплаты: дата по выписке — ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "accountant@demo.example");
      let form: Locator;
      if (width === 390) {
        await spaGoto(page, "/eds/payments");
        await page.getByRole("link", { name: "Показать счёт СЧ-2026/142 в боковом окне" }).click();
        form = page
          .getByRole("dialog", { name: /^Оплата/ })
          .getByRole("form", { name: "Подтверждение оплаты" });
      } else {
        await spaGoto(page, "/eds/payments?show=proofs");
        await page.getByRole("link", { name: /^Показать .* СЧ-2026\/145 в боковом окне/ }).click();
        form = page.locator(PANEL).getByRole("form", { name: "Подтверждение оплаты" });
      }
      await expect(form).toBeVisible();
      const date = form.getByLabel(/Дата/).first();
      await expect(date).toHaveValue(/^\d{2}\.\d{2}\.\d{4}$/);
      await fillDate(date, inDays(-1));
      await expectNoNativeFields(form);
      await settledScreenshot(page, "payment-confirm");
      await expectNoViolations(page, `подтверждение оплаты, ${String(width)}`);
    });

    test(`журнал аудита: период «с — по» — ${String(width)}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/audit");
      const filters = page.getByRole("search", { name: /Фильтры/ });
      await expect(filters).toBeVisible();
      await fillDate(page.getByLabel("С даты"), "2026-10-24");
      await fillDate(page.getByLabel("По дату"), "2026-10-31");
      await expect(page.getByLabel("С даты")).toHaveValue("24.10.2026");
      await expectNoNativeFields(filters);
      await settledScreenshot(page, "audit-filters");
      await expectNoViolations(page, `фильтры журнала, ${String(width)}`);
    });
  }
});
