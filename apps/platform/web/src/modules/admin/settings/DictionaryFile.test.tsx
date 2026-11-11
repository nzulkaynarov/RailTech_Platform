import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { readDictionaries } from "../../../mocks/dictionaries";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const PAGE = "/admin/dictionaries?list=doc%3Amail-types";

function upload(text: string): void {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("нет поля загрузки");
  const file = new File([text], "types.csv", { type: "text/csv" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Справочники файлом (решение владельца 2026-11-11)", () => {
  it("загрузка сначала проверяется: видно, что добавится и где ошибка; с ошибкой «Применить» недоступно", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("button", { name: "Скачать" })).toBeVisible();
    upload("code;name_ru\n;Жалоба покупателя\nnope;Ошибка\n");
    const dialog = await screen.findByRole("dialog", {
      name: "Типы входящих писем: загрузка файла",
    });
    expect(
      await within(dialog).findByText("Добавится: 1, изменится: 0, без изменений: 0, с ошибкой: 1"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("нет такого кода")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Применить/ })).toBeDisabled();
    expect(readDictionaries()["mail-types"]).toHaveLength(9);
  });

  it("файл без ошибок применяется, список обновляется", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    await screen.findByRole("button", { name: "Скачать" });
    upload("code;name_ru;name_uz;name_en\nspam;Спам;Spam;Junk mail\n");
    const dialog = await screen.findByRole("dialog", {
      name: "Типы входящих писем: загрузка файла",
    });
    expect(
      await within(dialog).findByText("Добавится: 0, изменится: 1, без изменений: 0, с ошибкой: 0"),
    ).toBeInTheDocument();
    const apply = within(dialog).getByRole("button", { name: /Применить/ });
    await waitFor(() => {
      expect(apply).toBeEnabled();
    });
    fireEvent.click(apply);
    await waitFor(() => {
      expect(readDictionaries()["mail-types"].find((t) => t.code === "spam")?.name.en).toBe(
        "Junk mail",
      );
    });
  });
});
