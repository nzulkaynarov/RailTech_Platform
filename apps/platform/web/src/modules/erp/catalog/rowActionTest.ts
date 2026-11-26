import { fireEvent, screen, within } from "@testing-library/react";

/** Действие строки: основное — кнопка, остальные — в меню «Ещё». */
export async function clickRowAction(row: HTMLElement, name: string): Promise<void> {
  const direct = within(row).queryByRole("button", { name });
  if (direct) {
    fireEvent.click(direct);
    return;
  }
  fireEvent.click(within(row).getByRole("button", { name: "Ещё" }));
  fireEvent.click(await screen.findByRole("menuitem", { name }));
}
