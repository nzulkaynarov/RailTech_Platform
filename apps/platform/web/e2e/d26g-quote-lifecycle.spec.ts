import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { confirmDialog, loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// Находки гейта D2-6 на MSW (SPEC-v3 §3.3): D26G-2 — версия 1 КП, возвращённая на доработку, в истории «Заменена версией 2»,
// версия 2 показывает состав и одобряется; D26G-3 — клиент отклонил КП: у менеджера строка с причиной, на расчёте — «Клиент
// отклонил КП», «Новая версия КП» и «Отказ по заявке»; D26G-5 — наценка даёт цену до сума. Обе ширины, axe — 0 нарушений.
const WIDTHS = [1440, 390] as const;
const UNIVERSAL = "universal@demo.example";
const DIRECTOR = "director@demo.example";
const REJECTED = "ЗВ-2026-109";
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

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function signInAt(page: Page, email: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(`window.localStorage.clear()`);
  }
  await loginAndWait(page, email);
}

test.describe("D26G: жизненный цикл КП — доработка, отказ клиента, цена клиенту", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`клиент отклонил КП: строка менеджеру, новая версия КП, ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, UNIVERSAL, width);
      const row = page
        .getByRole("region", { name: "Что сделать сейчас" })
        .getByRole("listitem")
        .filter({ hasText: `Клиент отклонил КП по заявке ${REJECTED}` });
      await expect(row).toHaveCount(1);
      await expect(row).toContainText("Причина: Дорого: у конкурента на 7 % ниже");
      await shot(page, "queue-client-rejected");
      await expectNoViolations(page, `очередь ${String(width)}`);

      await row.getByRole("link", { name: /Открыть/ }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${REJECTED}` }),
      ).toBeVisible();
      await expect(page.getByText(/Клиент отклонил КП КП-2026\/119 \(версия 1\)/)).toBeVisible();
      await expect(page.getByText("КП отклонено клиентом").first()).toBeVisible();
      await expect(page.getByText(/Директор отклонил/)).toHaveCount(0);
      await shot(page, "calc-client-rejected");
      await expectNoViolations(page, `расчёт после отказа клиента ${String(width)}`);

      await page.getByRole("button", { name: "Новая версия КП" }).click();
      await expect(page.getByText("В работе").first()).toBeVisible();
      await expect(page.getByText(/Клиент отклонил КП КП-2026/)).toHaveCount(0);
      await shot(page, "calc-new-version");
      await expectNoViolations(page, `новая версия ${String(width)}`);

      // Новая версия — тот же номер КП (SPEC-v3 §2.2): виза и «Расчёт готов» → у директора КП-2026/119
      await page.getByRole("button", { name: /Подтвердить строку «Привод/ }).click();
      await page.getByRole("button", { name: "Расчёт готов" }).click();
      await expect(page.getByText(/Черновик КП КП-2026\/119, версия 2, у директора/)).toBeVisible();
      await shot(page, "calc-new-version-ready");
    });

    test(`отказ по заявке с причиной закрывает заявку, ${String(width)}`, async ({ page }) => {
      await signInAt(page, UNIVERSAL, width);
      await spaGoto(page, `/erp/calc/${encodeURIComponent(REJECTED)}`);
      await page.getByRole("button", { name: "Отказ по заявке" }).click();
      const dialog = page.getByRole("dialog", { name: `Отказ по заявке ${REJECTED}` });
      await expect(dialog).toBeVisible();
      const submit = dialog.getByRole("button", { name: "Закрыть заявку отказом" });
      await expect(submit).toBeDisabled();
      await dialog.getByLabel("Причина отказа").fill("Клиент купил у конкурента");
      await shot(page, "calc-lost-dialog");
      await expectNoViolations(page, `диалог отказа ${String(width)}`);
      await submit.click();
      await expect(page.getByText("Заявка закрыта с отказом. Резерв по ней снят.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Новая версия КП" })).toHaveCount(0);
      await shot(page, "calc-lost");
    });

    test(`КП после доработки: версия 1 заменена, версия 2 одобряется, ${String(width)}`, async ({
      page,
    }) => {
      await signInAt(page, DIRECTOR, width);
      await spaGoto(page, "/eds/drafts/40000000-0000-4000-8000-000000001150");
      await expect(page.getByText(/Это версия 1 — её заменила версия 2/)).toBeVisible();
      await shot(page, "quote-v1-superseded");
      await expectNoViolations(page, `версия 1 ${String(width)}`);

      await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
      await expect(page.getByText("Версия 2").first()).toBeVisible();
      await expect(page.getByText("Привод стрелочный СП-6").first()).toBeVisible();
      await expect(page.getByText(/Это версия/)).toHaveCount(0);
      await shot(page, "quote-v2-current");
      await expectNoViolations(page, `версия 2 ${String(width)}`);
      if (width >= 768) {
        const form = page.locator(PANEL).getByRole("form", { name: "Одобрение КП" });
        const approve = form.getByRole("button", { name: "Одобрить КП" });
        await expect(approve).toBeEnabled();
        await approve.click();
        await confirmDialog(page);
        await expect(page.getByText("Одобрено").first()).toBeVisible();
      }
    });
  }

  for (const width of WIDTHS) {
    test(`наценка даёт цену клиенту, округлённую до сума, ${String(width)}`, async ({ page }) => {
      await signInAt(page, "supply@demo.example", width);
      await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-097")}`);
      const name = "Перевод стрелочный Р65 марки 1/11";
      const markup = page.getByLabel(`Наценка, %: ${name}`);
      await markup.fill("15.56");
      await markup.press("Enter");
      await expect(page.getByLabel(`Цена клиенту без НДС за единицу для «${name}»`)).toHaveValue(
        /^104\s004\s000/,
      );
      await shot(page, "calc-markup");
      await expectNoViolations(page, `наценка ${String(width)}`);
    });
  }
});
