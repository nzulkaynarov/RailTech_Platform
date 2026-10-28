import { waitFor } from "@testing-library/react";
import { beforeEach } from "vitest";

import { resetCompanyMock } from "../mocks/fixtures/company";
import { resetErpCatalog } from "../mocks/fixtures/erpCatalog";
import { resetRoles } from "../mocks/fixtures/roles";
import { setupBotTests } from "./botKit";

export { renderAt, signIn } from "./botKit";

/** Оснастка тестов «Расчёт · Номенклатура и поставщики» и «Техдокументация»: чистые моки каталога, компании и ролей. */
export function setupCatalogTests(width = 1440): void {
  setupBotTests(width);
  beforeEach(() => {
    resetErpCatalog();
    resetCompanyMock();
    resetRoles();
  });
}

/**
 * Окно (`Modal`) по заголовку. В тестах antd даёт всем окнам один `aria-labelledby="test-id"`, поэтому, пока открыта
 * панель (`Drawer`), имя диалога по роли у окна над ней определяется неверно — ищем по заголовку окна.
 */
export async function findModal(title: string | RegExp): Promise<HTMLElement> {
  return waitFor(() => {
    const hit = Array.from(document.querySelectorAll<HTMLElement>(".ant-modal")).find((modal) => {
      const text = modal.querySelector(".ant-modal-title")?.textContent ?? "";
      return typeof title === "string" ? text === title : title.test(text);
    });
    if (!hit) throw new Error(`нет окна «${String(title)}»`);
    return hit;
  });
}

export async function modalClosed(title: string | RegExp): Promise<void> {
  await waitFor(() => {
    const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-modal")).some((modal) => {
      const text = modal.querySelector(".ant-modal-title")?.textContent ?? "";
      return typeof title === "string" ? text === title : title.test(text);
    });
    if (open) throw new Error(`окно «${String(title)}» ещё открыто`);
  });
}
