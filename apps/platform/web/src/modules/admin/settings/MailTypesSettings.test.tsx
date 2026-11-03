import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { readDictionaries } from "../../../mocks/dictionaries";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { resetInboundMailMock } from "../../../mocks/inboundMail";
import { readRules } from "../../../mocks/mailTypes";
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
  resetInboundMailMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const PAGE = "/admin/dictionaries?list=doc%3Amail-types";

async function rowOf(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name, { selector: "b" });
  return cell.closest("tr") as HTMLElement;
}

describe("Настройки · Процессы · Справочники · Типы входящих писем (MAIL-TYPES)", () => {
  it("раздел «Почта» слева; девять стартовых типов с действием по умолчанию из закрытого списка; использованный не удаляется", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("heading", { level: 1, name: "Справочники" })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Справочники по разделам" });
    expect(within(nav).getByText("Почта")).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Типы входящих писем" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await rowOf("Запрос клиента")).toHaveTextContent("Создать лид → менеджеру");
    expect(await rowOf("КП или прайс поставщика")).toHaveTextContent(
      "Загрузить прайс или КП поставщика",
    );
    expect(await rowOf("Спам")).toHaveTextContent("В «Подозрительные» (спам)");
    expect(readDictionaries()["mail-types"]).toHaveLength(9);
    // «Документ поставщика» уже стоит у демо-писем — удалить нельзя, только скрыть; «Приглашение на встречу» не использовано
    expect(
      screen.queryByRole("button", { name: "Удалить: Документ поставщика (договор, акт сверки)" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Удалить: Приглашение на встречу" })).toBeEnabled();
  });

  it("добавляет тип: действие по умолчанию обязательно и берётся из закрытого списка, код создаёт система", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    fireEvent.click(await screen.findByRole("button", { name: "Добавить значение" }));
    const dialog = await screen.findByRole("dialog", { name: "Новое значение" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Название по-русски" }), {
      target: { value: "Жалоба покупателя" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(await within(dialog).findByText("Выберите значение")).toBeInTheDocument();

    fireEvent.mouseDown(within(dialog).getByRole("combobox", { name: "Действие по умолчанию" }));
    fireEvent.click(await screen.findByTitle("Передать бухгалтеру"));
    // вид документа при регистрации — необязательный, варианты из справочника «Виды входящих документов»
    fireEvent.mouseDown(
      within(dialog).getByRole("combobox", { name: "Вид документа при регистрации" }),
    );
    fireEvent.click(await screen.findByTitle("Письмо контрагента"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    const row = await rowOf("Жалоба покупателя");
    expect(row).toHaveTextContent("Передать бухгалтеру");
    const stored = readDictionaries()["mail-types"].at(-1);
    expect(stored?.attrs).toEqual({
      default_action: "to_accountant",
      color: "default",
      icon: "mail",
      letter_kind: "counterparty",
    });
  });

  it("правила отправителей: добавить «soliq.uz → официальное», увидеть в таблице, удалить", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("heading", { name: "Правила отправителей" })).toBeVisible();
    expect(await screen.findByText("Правил нет")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "Адрес или домен" }), {
      target: { value: "*@Soliq.uz" },
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Тип" }));
    fireEvent.click(await screen.findByTitle("Официальное письмо (госорган, банк, налоговая)"));
    fireEvent.click(screen.getByRole("button", { name: "Добавить правило" }));
    const rule = await screen.findByText("soliq.uz", { selector: "b" });
    expect(rule.closest("tr")).toHaveTextContent("Официальное письмо (госорган, банк, налоговая)");
    expect(readRules().map((r) => r.pattern)).toEqual(["soliq.uz"]);

    fireEvent.click(screen.getByRole("button", { name: "Удалить правило: soliq.uz" }));
    await waitFor(() => {
      expect(readRules()).toEqual([]);
    });
    expect(await screen.findByText("Правил нет")).toBeVisible();
  });

  it("директор видит справочник и правила, но не меняет их", async () => {
    signInAs("director@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("heading", { level: 1, name: "Справочники" })).toBeVisible();
    expect(await rowOf("Запрос клиента")).toBeVisible();
    expect(screen.getByRole("button", { name: "Добавить значение" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Добавить правило" })).toBeNull();
  });
});
