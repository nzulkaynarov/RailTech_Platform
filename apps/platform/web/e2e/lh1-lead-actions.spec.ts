import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";

// LH-1 «Ручки лида» на MSW: у лида, который ведёт менеджер, — одно меню «Закрыть» («Заключено», «Отказ», «Спам», «Тест»,
// «Дубль»), «Передать коллеге», правка контактов в карточке и «Открыть заново» у закрытого. Каждое действие меняет экран, а не
// всплывающее сообщение. Обе ширины, axe на меню, окне и карточке.
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

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function signInAt(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) await page.evaluate(`window.localStorage.clear()`);
  await loginAndWait(page, "manager@demo.example");
}

test.describe("LH-1: ручки лида", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`меню «Закрыть», отказ с причиной, «Открыть заново» — ${String(width)}`, async ({
      page,
    }) => {
      const mobile = width < 768;
      await signInAt(page, width);
      await spaGoto(page, "/crm/messages?lead=L-2050");
      await expect(page.getByRole("heading", { level: 2, name: "Тимур Образцов" })).toBeVisible();
      if (mobile) await page.getByRole("button", { name: "Карточка лида" }).click();
      const scope = mobile ? page.getByRole("dialog") : page;

      // Одно меню вместо рядов кнопок
      await scope.getByRole("button", { name: /^Закрыть: / }).click();
      await expect(page.getByRole("menuitem", { name: "Отказ" })).toBeVisible();
      await expect(page.getByRole("menuitem", { name: "Дубль" })).toBeVisible();
      await shot(page, "close-menu");
      await expectNoViolations(page, `меню «Закрыть» ${String(width)}`);

      // «Отказ» не уходит без причины; причина — из справочника
      await page.getByRole("menuitem", { name: "Отказ" }).click();
      const dialog = page.getByRole("dialog", { name: "Отказ" });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Закрыть лид" }).click();
      await expect(dialog.getByText("Выберите причину отказа")).toBeVisible();
      await shot(page, "close-dialog");
      await expectNoViolations(page, `окно «Отказ» ${String(width)}`);
      await chooseOption(dialog.getByRole("combobox"), "Дорого");
      await dialog.getByRole("button", { name: "Закрыть лид" }).click();
      await expect(dialog).toBeHidden();

      // Лида в очереди «Ждут ответа» больше нет; карточка в «Лидах» — «Отказ» и «Открыть заново»
      await spaGoto(page, "/crm/leads?lead=L-2050&panel=open&tab=card");
      const card = page.getByRole("heading", { level: 3, name: "Отабек Демо" });
      await expect(card).toBeVisible();
      const reopen = page.getByRole("button", { name: "Открыть заново" });
      await expect(reopen).toBeVisible();
      await shot(page, "closed-card");
      await expectNoViolations(page, `закрытая карточка ${String(width)}`);
      await reopen.click();
      await expect(page.getByRole("button", { name: /^Закрыть: / })).toBeVisible();
    });

    test(`правка контактов и дубль — ${String(width)}`, async ({ page }) => {
      await signInAt(page, width);
      await spaGoto(page, "/crm/leads?lead=L-2050&panel=open&tab=card");
      await expect(page.getByRole("heading", { level: 3, name: "Отабек Демо" })).toBeVisible();
      await page.getByRole("button", { name: /^Изменить: / }).click();
      await page.getByLabel("Телефон").fill("+998 90 000 00 77");
      await page.getByLabel("Компания").fill("ООО Новая");
      await shot(page, "edit-contacts");
      await expectNoViolations(page, `правка контактов ${String(width)}`);
      await page.getByRole("button", { name: "Сохранить", exact: true }).click();
      // номер уже у другого лида: правка сохранена, предупреждение — под контактами
      const warning = page
        .getByRole("status")
        .filter({ hasText: "Такой номер или почта уже есть" });
      await expect(warning).toBeVisible();
      await expect(page.getByText("+998900000077").first()).toBeVisible();
      await shot(page, "edit-duplicate-warning");
      await expectNoViolations(page, `предупреждение о дубле ${String(width)}`);
    });
  }
});
