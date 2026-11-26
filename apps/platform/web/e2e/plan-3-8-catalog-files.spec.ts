import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { chooseOption } from "./support/fields";

// План 3.8 на MSW: категории выгружаются и загружаются файлом прямо со своей вкладки (дерево остаётся), производители —
// обычный справочник в «Настройки · Справочники». Снимки 1440 с axe — E2E_SCREENSHOT_DIR (docs/screens/plan-3-8).
test("категории и производители файлом", async ({ page }) => {
  test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAndWait(page, "admin@demo.example");
  const dir = process.env["E2E_SCREENSHOT_DIR"];

  await spaGoto(page, "/admin/dictionaries?list=categories");
  await expect(page.getByRole("button", { name: "Скачать" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Загрузить" })).toBeVisible();
  // В общем списке справочников категории не дублируются: у них своя вкладка с деревом
  await expect(page.getByRole("link", { name: "Категории товаров" })).toHaveCount(0);
  await waitForMotionEnd(page);
  if (dir) await page.screenshot({ path: `${dir}/categories-file-1440.png` });
  await expectNoViolations(page, "категории: файл");

  // второго меню внутри страницы нет (SET-1): справочник выбирают из списка над таблицей
  await chooseOption(page.getByLabel("Справочники по разделам"), "Бренды");
  await expect(page.getByRole("cell", { name: "Демо-Завод", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать" })).toBeVisible();
  await waitForMotionEnd(page);
  if (dir) await page.screenshot({ path: `${dir}/manufacturers-1440.png` });
  await expectNoViolations(page, "бренды");
});
