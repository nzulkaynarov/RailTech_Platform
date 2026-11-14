import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { openStep } from "./support/fields";

// План 1.4 на MSW: исходящее письмо → «Подготовить текст» по поручению сотрудника вставляет черновик в редактор →
// «Перевести на английский» показывает перевод и обратный перевод рядом → «Вставить перевод». Снимки 1440 и 390 с axe —
// E2E_SCREENSHOT_DIR (docs/screens/plan-1-4).
const WIDTHS = [1440, 390] as const;

async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
    }
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
      ),
      `${name} ${String(width)}`,
    ).toEqual([]);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("помощник письма: черновик по поручению и перевод с обратным переводом", async ({ page }) => {
  await loginAndWait(page, "director@demo.example");
  await spaGoto(page, "/eds/new?type=letter");
  await page.getByLabel("Тема").fill("Срок поставки по договору 12");
  await openStep(page, "Текст и вложения");

  await page.getByRole("button", { name: "Подготовить текст" }).click();
  const draft = page.getByRole("dialog", { name: "Подготовить текст письма" });
  await draft.getByLabel("О чём письмо").fill("Подтвердить срок поставки");
  await draft.getByRole("button", { name: "Подготовить" }).click();
  const body = page.getByRole("textbox", { name: "Текст" });
  await expect(body).toContainText("Просим подтвердить срок поставки.");

  await page.getByRole("button", { name: "Перевести на английский" }).click();
  const translate = page.getByRole("dialog", { name: "Перевод на английский" });
  await expect(
    translate.getByRole("region", { name: "Обратный перевод — проверьте смысл" }),
  ).toContainText("Просим подтвердить срок поставки");
  await shoot(page, "letter-translate");

  await translate.getByRole("button", { name: "Вставить перевод" }).click();
  await expect(body).toContainText("Please confirm the delivery date.");
  await expect(page.getByRole("button", { name: "Перевести на английский" })).toHaveCount(0);
});
