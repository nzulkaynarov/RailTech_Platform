import type { Locator, Page } from "@playwright/test";

/** Меню строки «…» (`RowActions`): открыть меню строки `row` и выбрать пункт `item`. */
export async function pickRowAction(
  page: Page,
  row: string,
  item: string,
  scope: Page | Locator = page,
): Promise<void> {
  await scope.getByRole("button", { name: `Действия: ${row}` }).click();
  await page.getByRole("menuitem", { name: item, exact: true }).click();
}
