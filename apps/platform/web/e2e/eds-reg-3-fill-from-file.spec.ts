import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";
import { pickFiles } from "./support/fields";

// EDS-REG PR 3 на MSW: «Заполнить из файла» в «Зарегистрировать входящее» — PDF письма, предложенные поля с пометкой
// «Предложено ИИ», правка, скан читается по умолчанию («Деловая» политика, PD-BIZ); «ИИ-помощник» в Настройках. Модели нет —
// ответ мока вымышленный. axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR` → docs/screens/eds-reg-3/).
const WIDTHS = [1440, 390] as const;

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

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function fillFromFile(page: Page, name: string, mimeType: string): Promise<void> {
  // Новая форма: уйти со страницы и вернуться (тот же адрес форму не сбрасывает).
  await spaGoto(page, "/eds/inbox");
  // Форма сбрасывается, только если экран регистрации успел смениться: без ожидания два перехода подряд склеиваются, и
  // в форме остаётся прошлый файл (флейк CI: помощник читал прежний PDF вместо скана)
  await expect(page.getByRole("heading", { level: 1, name: "Входящие" })).toBeVisible();
  await spaGoto(page, "/eds/register");
  await expect(
    page.getByRole("heading", { level: 1, name: "Регистрация входящего документа" }),
  ).toBeVisible();
  await pickFiles(page.getByLabel("Файл документа"), {
    name,
    mimeType,
    buffer: Buffer.from("%PDF-1.4 demo"),
  });
  await expect(page.getByText("загружен")).toBeVisible();
  await page.getByRole("button", { name: "Заполнить из файла" }).click();
}

test.describe("EDS-REG · «Заполнить из файла»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("делопроизводитель заполняет форму из PDF; скан — по умолчанию и по настройке", async ({
    page,
  }) => {
    await loginAndWait(page, "registrar@demo.example");
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      // 1. PDF с текстом: поля предложены и помечены.
      await fillFromFile(page, "trebovanie-gni.pdf", "application/pdf");
      await expect(page.getByText(/Заполнено из файла: 8 полей/)).toBeVisible();
      await expect(page.getByLabel("Корреспондент", { exact: true })).toHaveValue(
        "ГНИ Демо-района",
      );
      await expect(page.getByText("Предложено ИИ", { exact: true })).toHaveCount(8);
      await page.getByLabel("Тема", { exact: true }).fill("Пояснения по НДС за III квартал");
      await expect(page.getByText("Предложено ИИ", { exact: true })).toHaveCount(7);
      await page.getByRole("heading", { level: 1 }).scrollIntoViewIfNeeded();
      await expectNoViolations(page, `register-filled ${String(width)}`);
      if (width === 390) await noHorizontalScroll(page);
      await settledScreenshot(page, "register-filled");
      await page.getByRole("group", { name: "Заполнить из файла" }).scrollIntoViewIfNeeded();
      await settledScreenshot(page, "register-ai-bar");

      // 2. Скан при «Деловой» политике (по умолчанию) читается, как PDF.
      await fillFromFile(page, "скан-письма.png", "image/png");
      await expect(page.getByText(/Заполнено из файла: 8 полей/)).toBeVisible();
      await expectNoViolations(page, `register-scan-on ${String(width)}`);
      await settledScreenshot(page, "register-scan-on");
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await signOut(page);

    // 3. Администратор: Настройки · Система · Расходы на ИИ, часть «Заполнить из файла» (SET-IA; старый адрес уводит
    // туда) — переключатель сканов включён, подпись про паспорта и личные документы (PD-BIZ).
    await loginAndWait(page, "admin@demo.example");
    await spaGoto(page, "/admin/docflow?tab=ai");
    await expect(page.getByRole("switch", { name: "Читать сканы и фото писем" })).toBeChecked();
    await expect(page.getByText("Паспорта и личные документы не загружайте.")).toBeVisible();
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await expectNoViolations(page, `settings-ai ${String(width)}`);
      await settledScreenshot(page, "settings-ai");
    }
  });
});
