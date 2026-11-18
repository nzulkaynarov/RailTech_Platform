import { expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СУЩ-2.5 на MSW (ADR-0028, макет «Контрагент», лист 2): одна карточка компании во всех ролях — роли-отметки, «Обзор»
// (люди, счета, бренды), «Заявки и проекты», «Товары поставщика». Снимки 1440 и 390 с axe.
const dir = process.env["E2E_SCREENSHOT_DIR"];

for (const width of [1440, 390] as const) {
  test(`карточка контрагента, ${String(width)}`, { tag: "@mobile" }, async ({ page }) => {
    test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/crm/clients?partner=2&panel=open&tab=card");
    const roles = page.getByRole("list", { name: "Роли" });
    await expect(roles.getByRole("button", { name: "✓ Поставщик" })).toBeVisible();
    await expect(roles.getByRole("button", { name: "✓ Изготовитель" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Товары поставщика" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({ path: `${dir}/card-supplier-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "карточка: товары поставщика");

    await page.getByRole("tab", { name: "Обзор" }).click();
    await expect(page.getByRole("heading", { name: "Люди" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Как изготовитель" })).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Как изготовитель" }).getByText("Рельс-Сталь"),
    ).toBeVisible();
    await waitForMotionEnd(page);
    if (dir)
      await page.screenshot({ path: `${dir}/card-overview-${String(width)}.png`, fullPage: true });
    await expectNoViolations(page, "карточка: обзор");
  });

  test(
    `карточка клиента — та же карточка, ${String(width)}`,
    { tag: "@mobile" },
    async ({ page }) => {
      test.skip(test.info().project.name !== "chromium", "ширины задаёт сам сценарий");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients/3?panel=open&tab=card");
      await expect(page.getByRole("list", { name: "Роли" }).getByText("Клиент")).toBeVisible();
      await expect(page.getByRole("tab", { name: "Заявки и проекты" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await waitForMotionEnd(page);
      if (dir)
        await page.screenshot({ path: `${dir}/card-client-${String(width)}.png`, fullPage: true });
      await expectNoViolations(page, "карточка клиента");
    },
  );
}
