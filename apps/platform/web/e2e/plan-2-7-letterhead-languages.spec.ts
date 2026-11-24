import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// План 2.7 (TPL-3) на MSW: «Бланк на узбекском и английском» в «Реквизитах и бланке». Снимок 1440 с axe —
// E2E_SCREENSHOT_DIR (docs/screens/plan-2-7).
test("бланк на узбекском и английском", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await loginAndWait(page, "admin@demo.example");
  await spaGoto(page, "/admin/company?part=brand");
  await page.getByRole("button", { name: /Бланк на узбекском и английском/ }).click();
  const uz = page.getByRole("group", { name: "Özbekça (UZ)" });
  await expect(uz.getByLabel("Должность подписанта")).toHaveValue("Direktor");
  await uz.getByLabel("Название компании").fill("«Demo Temir Yo‘l» MChJ");
  await uz.scrollIntoViewIfNeeded();
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/letterhead-languages-1440.png` });
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("iframe")
    .analyze();
  expect(results.violations.map((v) => v.id)).toEqual([]);
});
