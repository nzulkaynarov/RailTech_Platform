import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { rowActionItems } from "../../../test/rowActions";

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

/** ЕВ-2а: виды входящих писем и правила отправителей — часть страницы канала «Почта», а не «Справочников». */
const PAGE = "/admin/mail";

async function rowOf(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name, { selector: "b" });
  return cell.closest("tr") as HTMLElement;
}

describe("Настройки · Каналы · Почта · Типы входящих писем (MAIL-TYPES)", () => {
  it("виды писем — на странице «Почта», в «Справочниках» их больше нет; девять стартовых типов с действием по умолчанию из закрытого списка; использованный не удаляется", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
    expect(await rowOf("Запрос клиента")).toHaveTextContent("Создать лид → менеджеру");
    expect(await rowOf("КП или прайс партнёра")).toHaveTextContent(
      "Загрузить прайс или КП партнёра",
    );
    expect(await rowOf("Спам")).toHaveTextContent("В «Подозрительные» (спам)");
    expect(readDictionaries()["mail-types"]).toHaveLength(9);
    // «Документ партнёра» уже стоит у демо-писем — удалить нельзя, только скрыть; «Приглашение на встречу» не использовано
    expect(await rowActionItems("Документ партнёра (договор, акт сверки)")).not.toContain(
      "Удалить",
    );
    expect(await rowActionItems("Приглашение на встречу")).toContain("Удалить");
  });

  it("добавляет тип: действие по умолчанию обязательно и берётся из закрытого списка, код создаёт система", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    fireEvent.click(await screen.findByRole("button", { name: "Добавить значение" }));
    const dialog = await screen.findByRole("region", { name: "Новое значение" });
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

  it("старый адрес справочника уводит на «Почту»; в «Справочниках» раздела «Почта» нет", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/dictionaries?list=doc%3Amail-types");
    expect(await screen.findByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
    expect(await rowOf("Запрос клиента")).toBeVisible();
    cleanup();
    renderApp("/admin/dictionaries");
    const nav = await screen.findByRole("navigation", { name: "Справочники по разделам" });
    expect(within(nav).queryByText("Почта")).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Типы входящих писем" })).toBeNull();
  });

  it("директор страницу «Почта» не видит: канал — фундамент администратора (ЕВ-2а)", async () => {
    signInAs("director@demo.example");
    renderApp(PAGE);
    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Добавить правило" })).toBeNull();
  });
});
