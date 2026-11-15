import { fireEvent, screen, within } from "@testing-library/react";

/** Меню строки «…» (`RowActions`): открыть меню строки `row` и выбрать пункт `item`. */
export async function pickRowAction(
  row: string,
  item: string,
  scope: HTMLElement = document.body,
): Promise<void> {
  fireEvent.click(await within(scope).findByRole("button", { name: `Действия: ${row}` }));
  const menus = await screen.findAllByRole("menu");
  fireEvent.click(within(menus.at(-1) as HTMLElement).getByRole("menuitem", { name: item }));
}

/** Пункты меню строки `row` по порядку (меню закрывается); нет кнопки меню — пустой список. */
export async function rowActionItems(
  row: string,
  scope: HTMLElement = document.body,
): Promise<string[]> {
  const button = within(scope).queryByRole("button", { name: `Действия: ${row}` });
  if (!button) return [];
  fireEvent.click(button);
  const menus = await screen.findAllByRole("menu");
  const items = within(menus.at(-1) as HTMLElement)
    .getAllByRole("menuitem")
    .map((element) => element.textContent ?? "");
  fireEvent.click(button);
  return items;
}
