import { fireEvent, waitFor } from "@testing-library/react";

/** Нажать главную кнопку открытого окна подтверждения. */
export async function confirmDialog(): Promise<void> {
  const button = await waitFor(() => {
    const found = document.querySelector<HTMLElement>(".ant-modal-confirm-btns .ant-btn-primary");
    if (!found) throw new Error("нет окна подтверждения");
    return found;
  });
  fireEvent.click(button);
}
