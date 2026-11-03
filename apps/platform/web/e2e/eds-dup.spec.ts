import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { fillDate } from "./support/fields";
import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// EDS-DUP «Одно письмо — один входящий номер» на MSW: форма «Зарегистрировать входящее» в фоне находит то же письмо
// (корреспондент + исх. № + дата) и похожие; «Это другое письмо — зарегистрировать» просит причину; в карточке ВХ —
// «Это дубль ВХ-…» с «Что произойдёт», после — статус «Дубль» и ссылка на оригинал. Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";

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

async function expectFits(page: Page, context: string): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, context).toBeLessThanOrEqual(0);
}

async function signInAt(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
  }
  await loginAndWait(page, REGISTRAR);
}

test.describe("EDS-DUP: одно письмо — один входящий номер", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("форма находит то же письмо и похожие; «Это другое письмо» — с причиной", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, width);
      await spaGoto(page, "/eds/register");
      await expect(
        page.getByRole("heading", { level: 1, name: "Зарегистрировать входящее" }),
      ).toBeVisible();
      await page.getByLabel("Корреспондент", { exact: true }).fill('акб "Демо-Банк"');
      await page.getByLabel("Исходящий номер отправителя").fill("№ 12-07/881");
      await fillDate(page.getByLabel("Дата у отправителя"), "2026-10-18");

      const exact = page
        .getByRole("alert")
        .filter({ hasText: "Похоже, это письмо уже зарегистрировано" });
      await expect(exact).toBeVisible();
      await expect(exact.getByRole("link", { name: "ВХ-100/26" })).toBeVisible();
      await expect(exact.getByText("Принято к сведению")).toBeVisible();
      await exact.scrollIntoViewIfNeeded();
      await shot(page, "register-exact");
      await expectFits(page, `форма ${String(width)}`);
      await expectNoViolations(page, `то же письмо ${String(width)}`);

      await exact.getByRole("button", { name: "Это другое письмо — зарегистрировать" }).click();
      await expect(page.getByLabel("Почему это другое письмо")).toBeVisible();
      await page
        .getByLabel("Почему это другое письмо")
        .fill("Повторное письмо с исправленной суммой");
      await shot(page, "register-force");
      await expectNoViolations(page, `причина ${String(width)}`);

      await fillDate(page.getByLabel("Дата у отправителя"), "2026-10-19");
      const similar = page.getByRole("status").filter({ hasText: "Похожие письма" });
      await expect(similar).toBeVisible();
      await expect(similar.getByText(/тот же исх\. №/)).toBeVisible();
      await expect(exact).toHaveCount(0);
      await similar.scrollIntoViewIfNeeded();
      await shot(page, "register-similar");
      await expectNoViolations(page, `похожие ${String(width)}`);
    }
  });

  test("«Это дубль ВХ-…» закрывает письмо со ссылкой на оригинал", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, width);
      await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-108/26")}`);
      await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-108/26" })).toBeVisible();
      await page.getByRole("button", { name: "Это дубль" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Номер оригинала").fill("ВХ-100/26");
      await dialog.getByLabel("Комментарий").fill("Пришло дважды: почтой и курьером");
      await expect(dialog.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
      await shot(page, "mark-dialog");
      await expectNoViolations(page, `диалог ${String(width)}`);

      await dialog.getByRole("button", { name: "Отметить дублем" }).click();
      await expect(dialog).toHaveCount(0);
      const banner = page.getByRole("status").filter({ hasText: "Дубль письма" });
      await expect(banner.getByRole("link", { name: "ВХ-100/26" })).toBeVisible();
      await expect(
        page.getByText("Дубль ВХ-100/26: Пришло дважды: почтой и курьером"),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Это дубль" })).toHaveCount(0);
      await page.evaluate("window.scrollTo(0, 0)");
      await shot(page, "card-duplicate");
      await expectFits(page, `карточка ${String(width)}`);
      await expectNoViolations(page, `дубль ${String(width)}`);
    }
  });
});
