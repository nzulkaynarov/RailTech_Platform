import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect } from "vitest";

/**
 * Поля Платформы в тестах (UX-2a): дата — `DateField` (antd DatePicker), выбор — antd `Select`. Системных полей нет,
 * поэтому `fireEvent.change(input, { target: { value: "2026-10-31" } })` больше не работает.
 */

/** Набрать дату в `DateField` с клавиатуры: ключ `YYYY-MM-DD` → `ДД.ММ.ГГГГ` и Enter; пустая строка — очистка. */
export function fillDate(input: HTMLElement, iso: string): void {
  if (iso === "") {
    const clear = input.closest(".ant-picker")?.querySelector(".ant-picker-clear");
    if (clear) {
      fireEvent.mouseDown(clear);
      fireEvent.mouseUp(clear);
      fireEvent.click(clear);
    }
    return;
  }
  const [year, month, day] = iso.split("-");
  fireEvent.mouseDown(input);
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: `${day ?? ""}.${month ?? ""}.${year ?? ""}` } });
  fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13, charCode: 13 });
  fireEvent.blur(input);
}

/** Открыть antd `Select` и выбрать пункт по подписи (точно или началом подписи до « · »). */
export async function chooseOption(combobox: HTMLElement, label: string): Promise<void> {
  fireEvent.mouseDown(combobox);
  const option = await waitFor(() => {
    const found = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => {
      const title = item.getAttribute("title") ?? item.textContent;
      return title === label || title.startsWith(`${label} · `);
    });
    expect(found, `пункт «${label}»`).toBeDefined();
    return found as HTMLElement;
  });
  fireEvent.click(option);
}

/** Подпись выбранного пункта antd `Select` (пусто — ничего не выбрано). */
export function selectedLabel(combobox: HTMLElement): string {
  return (
    combobox
      .closest(".ant-select")
      ?.querySelector(".ant-select-selection-item")
      ?.getAttribute("title") ?? ""
  );
}

/** Ввести поисковую строку в поле выбора компании (ЕД-6): поиск идёт с задержкой, подсказки приходят позже. */
export function searchCompany(combobox: HTMLElement, query: string): void {
  fireEvent.mouseDown(combobox);
  fireEvent.change(combobox, { target: { value: query } });
}

/** Выбрать компанию в `CompanyPicker`: найти по запросу и нажать строку с названием. */
export async function pickCompany(
  combobox: HTMLElement,
  query: string,
  name: string,
): Promise<void> {
  searchCompany(combobox, query);
  const option = await waitFor(() => {
    const found = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.getAttribute("title") === name);
    expect(found, `компания «${name}»`).toBeDefined();
    return found as HTMLElement;
  });
  fireEvent.click(option);
}

/** Компании нет среди контрагентов: «Завести» последней строкой, короткая форма, «Завести» — и она выбрана. */
export async function addCompany(combobox: HTMLElement, name: string, inn = ""): Promise<void> {
  searchCompany(combobox, name);
  const row = await waitFor(() => {
    const found = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.textContent === `Завести «${name.trim()}»`);
    expect(found, "строка «Завести»").toBeDefined();
    return found as HTMLElement;
  });
  fireEvent.click(row);
  const sheet = await screen.findByRole("dialog", { name: "Новая компания" });
  if (inn) fireEvent.change(within(sheet).getByLabelText("ИНН"), { target: { value: inn } });
  fireEvent.click(within(sheet).getByRole("button", { name: "Завести" }));
  await waitFor(() => {
    expect(screen.queryByRole("dialog", { name: "Новая компания" })).toBeNull();
  });
}
