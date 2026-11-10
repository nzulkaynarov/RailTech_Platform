import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetDictionariesMock } from "../../../mocks/dictionaries";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession } from "../../../mocks/mockSession";
import { readSigningAuthorities, resetSigningMock } from "../../../mocks/signing";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { chooseOption, fillDate } from "../../../test/fields";
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
  resetSigningMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const heading = () => screen.findByRole("heading", { level: 1, name: "Права подписи" });

async function rowOf(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name, { selector: "b" });
  return cell.closest("tr") as HTMLElement;
}

async function showAll(): Promise<void> {
  fireEvent.click(screen.getByText("Все", { selector: ".ant-segmented-item-label" }));
  await waitFor(() => {
    expect(screen.getAllByText("Отозвано", { selector: ".ant-tag" }).length).toBeGreaterThan(0);
  });
}

describe("Настройки · Права подписи (SIGN-2, ADR-0024)", () => {
  it("администратор видит действующие полномочия: основание, лимит, срок и «истекает через N дней»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/signing");
    await heading();
    const director = await rowOf("Демо Директоров");
    expect(director).toHaveTextContent("Устав");
    expect(director).toHaveTextContent("Без лимита");
    expect(director).toHaveTextContent("без срока окончания");
    expect(director).toHaveTextContent("Действует");
    const manager = await rowOf("Демо Менеджеров");
    expect(manager).toHaveTextContent("Доверенность № 17");
    expect(manager).toHaveTextContent("50 000 000 сум");
    expect(manager).toHaveTextContent("Скоро истекает");
    expect(manager).toHaveTextContent("истекает через 14 дней");
    expect(await rowOf("Демо Бухгалтеров")).toHaveTextContent("Приказ № 12-к");
    // истёкшее и отозванное — только по фильтру «Все»
    expect(screen.queryByText("Демо Снабженцев", { selector: "b" })).toBeNull();
    expect(screen.queryByText("Демо Инженеров", { selector: "b" })).toBeNull();
  });

  it("фильтр «Все» показывает истёкшее и отозванное словами", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/signing");
    await heading();
    await showAll();
    expect(await rowOf("Демо Снабженцев")).toHaveTextContent("Срок вышел");
    expect(await rowOf("Демо Инженеров")).toHaveTextContent("Отозвано");
  });

  it("пункт есть в меню Настроек, директору без права страница недоступна", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/signing");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Нет доступа" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Права подписи" })).toBeNull();
  });

  it("выдаёт приказ: номер и дата обязательны, запись появляется в списке и в журнале", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/signing");
    await heading();
    fireEvent.click(await screen.findByRole("button", { name: "Выдать полномочие" }));
    const drawer = await screen.findByRole("dialog", { name: "Выдать полномочие подписи" });
    await chooseOption(
      within(drawer).getByRole("combobox", { name: "Сотрудник" }),
      "Демо Снабженцев",
    );
    await chooseOption(within(drawer).getByRole("combobox", { name: "Что подписывает" }), "Счёт");
    fireEvent.click(within(drawer).getByRole("radio", { name: "Приказ" }));
    // пока номер и дата пусты — форма не уходит
    fireEvent.click(within(drawer).getByRole("button", { name: "Сохранить" }));
    expect(await within(drawer).findAllByText("Заполните поле")).not.toHaveLength(0);
    expect(readSigningAuthorities()).toHaveLength(5);

    fireEvent.change(within(drawer).getByRole("textbox", { name: "Номер" }), {
      target: { value: "21-к" },
    });
    fillDate(within(drawer).getByLabelText("Дата выдачи"), "2026-10-01");
    fireEvent.click(within(drawer).getByRole("button", { name: "Сохранить" }));

    const row = await rowOf("Демо Снабженцев");
    expect(row).toHaveTextContent("Приказ № 21-к от 01.10.2026");
    const stored = readSigningAuthorities().at(-1);
    expect(stored?.kinds).toEqual(["invoice"]);
    expect(stored?.journal.map((entry) => entry.action)).toEqual(["issued"]);
  });

  it("отзывает полномочие: причина обязательна, блок «Что произойдёт», потом «Отозвано»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/signing");
    await heading();
    fireEvent.click(
      await screen.findByRole("button", { name: "Открыть полномочие: Демо Менеджеров" }),
    );
    const drawer = await screen.findByRole("dialog", { name: "Полномочие: Демо Менеджеров" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Отозвать" }));
    // у окна и бокового окна в тестах один и тот же id заголовка (`useId`), поэтому окно ищем по тексту заголовка
    const title = await screen.findByText("Отозвать полномочие: Демо Менеджеров");
    const modal = title.closest<HTMLElement>('[role="dialog"]') as HTMLElement;
    fireEvent.click(within(modal).getByRole("button", { name: "Отозвать" }));
    expect(await within(modal).findByText("Укажите причину (от 3 знаков)")).toBeInTheDocument();
    fireEvent.change(within(modal).getByRole("textbox", { name: "Причина" }), {
      target: { value: "Доверенность отозвана приказом" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Отозвать" }));

    await waitFor(() => {
      expect(readSigningAuthorities().find((item) => item.revoked)?.revoked?.reason).toBe(
        "Доверенность отозвана приказом",
      );
    });
    await waitFor(() => {
      expect(screen.queryByText("Демо Менеджеров", { selector: "b" })).toBeNull();
    });
    await showAll();
    expect(await rowOf("Демо Менеджеров")).toHaveTextContent("Отозвано");
  });

  it("проверка правил: сумма выше лимита доверенности — подпишет только руководитель", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/signing");
    await heading();
    const card = (
      await screen.findByText("Кто вправе подписать", { selector: ".ant-card-head-title" })
    ).closest(".ant-card") as HTMLElement;
    await chooseOption(
      within(card).getByRole("combobox", { name: "Вид документа" }),
      "Исходящее письмо",
    );
    fireEvent.change(within(card).getByRole("spinbutton", { name: "Сумма" }), {
      target: { value: "60000000" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Проверить" }));
    const result = await within(card).findByRole("heading", { name: "Подпишет" });
    const section = result.closest(".pf-sign-result") as HTMLElement;
    expect(
      within(section).getAllByText("Демо Директоров", { exact: false }).length,
    ).toBeGreaterThan(0);
    expect(section).toHaveTextContent("Демо Менеджеров: сумма превышает лимит");
  });

  it("пустой реестр: подсказка предлагает директора из бланка", async () => {
    signInAs("admin@demo.example");
    window.localStorage.setItem("rt-pf-mock-signing", "[]");
    renderApp("/admin/signing");
    await heading();
    expect(
      await screen.findByText("Пока никто не вправе подписывать документы"),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить: Демо Директоров" }));
    const drawer = await screen.findByRole("dialog", { name: "Выдать полномочие подписи" });
    expect(within(drawer).getByRole("radio", { name: "Устав" })).toBeChecked();
    await waitFor(() => {
      expect(
        within(drawer).getAllByText("Демо Директоров", { exact: false }).length,
      ).toBeGreaterThan(0);
    });
  });
});
