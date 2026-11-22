import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// Замечание владельца 2026-11-22: при закреплённом рядом боковом окне рабочая область узкая, и «Почта адресата» в форме
// письма сжималась до одного слова в строке. Ширину колонок форма теперь считает от себя, а не от окна браузера.
const dir = process.env["E2E_SCREENSHOT_DIR"];

test("письмо: закреплённое боковое окно не сжимает поля формы", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширину задаёт сам сценарий");
  await page.setViewportSize({ width: 1700, height: 1000 });
  await loginAndWait(page, "director@demo.example");
  await spaGoto(page, "/eds/new?type=letter&panel=open");
  await expect(page.getByRole("heading", { level: 1, name: "Исходящее письмо" })).toBeVisible();

  const panel = page.getByRole("complementary", { name: "Боковое окно" });
  await page.getByRole("button", { name: "Закрепить рядом с таблицей" }).click();
  await expect(panel).toHaveClass(/pf-panel-docked/);
  await waitForMotionEnd(page);

  // поле почты не уже 240 px: подсказка читается строкой, а не столбиком слов
  const email = page.getByLabel("Почта адресата", { exact: true });
  const emailBox = await email.boundingBox();
  expect(emailBox?.width ?? 0).toBeGreaterThanOrEqual(240);
  // горизонтальной прокрутки рабочей области нет
  expect(
    await page.evaluate<boolean>(
      `(() => { const m = document.getElementById("main-content"); return m.scrollWidth <= m.clientWidth + 1; })()`,
    ),
  ).toBe(true);

  if (dir) await page.screenshot({ path: `${dir}/letter-form-docked-1700.png` });
  await expectNoViolations(page, "письмо при закреплённом окне");
});
