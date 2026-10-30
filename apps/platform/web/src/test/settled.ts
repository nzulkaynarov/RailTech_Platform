import { waitFor } from "@testing-library/react";
import { expect } from "vitest";

/**
 * Список показал данные с новыми условиями (UX-1c, S8): при смене фильтра или вкладки прежние строки остаются на экране,
 * пока не придёт ответ (`DataBlock` с `aria-busy`). Проверки «этой строки больше нет» — после этого ожидания.
 */
export async function listSettled(): Promise<void> {
  await waitFor(() => {
    expect(document.querySelector(".pf-data-block[aria-busy]")).toBeNull();
  });
}
