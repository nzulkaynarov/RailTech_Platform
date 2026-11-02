import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { readDictionaries, resetDictionariesMock } from "../../../mocks/dictionaries";
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
  resetDictionariesMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const heading = () => screen.findByRole("heading", { level: 1, name: "Документооборот" });

async function rowOf(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name, { selector: "b" });
  return cell.closest("tr") as HTMLElement;
}

describe("Настройки · Документооборот · Справочники (EDS-REG)", () => {
  it("администратор видит стартовые виды документа с полями вида; пункт есть в меню", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/docflow");
    expect(await heading()).toBeInTheDocument();
    const tax = await rowOf("Требование или уведомление ГНК");
    expect(tax).toHaveTextContent("Да");
    expect(tax).toHaveTextContent("3");
    expect(tax).toHaveTextContent("Действует");
    expect(await rowOf("Письмо банка")).toHaveTextContent("по общему правилу");
    expect(screen.getAllByRole("link", { name: "Документооборот" }).length).toBeGreaterThan(0);
    // Письмо банка есть у демо-писем — удалить нельзя, только скрыть.
    expect(screen.queryByRole("button", { name: "Удалить: Письмо банка" })).toBeNull();
    expect(screen.getByRole("button", { name: "Удалить: Письмо поставщика" })).toBeEnabled();
  });

  it("добавляет вид документа: код из названия, «срочный» и срок; значение в конце списка", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/docflow");
    await heading();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить значение" }));
    const dialog = await screen.findByRole("dialog", { name: "Новое значение" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Название по-русски" }), {
      target: { value: "Претензия покупателя" },
    });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Срочный" }));
    fireEvent.change(within(dialog).getByRole("spinbutton", { name: "Срок исполнения, дней" }), {
      target: { value: "7" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    const row = await rowOf("Претензия покупателя");
    expect(row).toHaveTextContent("7");
    const stored = readDictionaries()["letter-kinds"].at(-1);
    expect(stored?.code).toBe("pretenziya_pokupatelya");
    expect(stored?.attrs).toEqual({ urgent: true, due_days: 7 });
  });

  it("скрывает использованный способ получения и возвращает; порядок — стрелками", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/docflow");
    await heading();
    fireEvent.click(await screen.findByText("Способы получения"));
    const post = await rowOf("Почта");
    fireEvent.click(within(post).getByRole("button", { name: "Скрыть: Почта" }));
    await waitFor(async () => {
      expect(await rowOf("Почта")).toHaveTextContent("Скрыто");
    });
    expect(readDictionaries()["receipt-methods"].find((i) => i.code === "post")?.active).toBe(
      false,
    );
    fireEvent.click(screen.getByRole("button", { name: "Выше: Почта" }));
    await waitFor(() => {
      expect(readDictionaries()["receipt-methods"][0]?.code).toBe("post");
    });
  });

  it("директор смотрит без правки", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/docflow");
    await heading();
    expect(await screen.findByText(/Только просмотр/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Добавить значение" })).toBeDisabled();
  });
});
