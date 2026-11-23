import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import { readZones, resetZonesMock } from "../../../mocks/zones";
import i18n from "../../../shared/i18n";
import { chooseOption } from "../../../test/fields";
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
  resetZonesMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const heading = () => screen.findByRole("heading", { level: 1, name: "Зоны ответственности" });

async function rowOf(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name, { selector: "b" });
  return cell.closest("tr") as HTMLElement;
}

async function openZone(name: string): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: `Открыть зону «${name}»` }));
  return screen.findByRole("region", { name: `Зона «${name}»` });
}

describe("Настройки · Зоны ответственности (ЕВ-З)", () => {
  it("девять зон из зерна без людей: «Не назначен» и «Нет ответственного» в каждой строке", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/zones");
    await heading();
    const finance = await rowOf("Финансы");
    expect(finance).toHaveTextContent("Счета, оплаты, визы бухгалтера, дебиторка.");
    expect(finance).toHaveTextContent("Не назначен");
    expect(finance).toHaveTextContent("Нет ответственного");
    expect(screen.getAllByText("Нет ответственного", { selector: ".ant-tag" })).toHaveLength(9);
    for (const name of ["Право", "Продажи", "Первый контакт", "Делопроизводство", "Снабжение"]) {
      expect(await rowOf(name)).toBeInTheDocument();
    }
    expect(screen.getByText(/уведомления и согласования они не направляют/)).toBeInTheDocument();
  });

  it("директор назначает человека и основание: строка и проблема меняются по фактам", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/zones");
    await heading();
    // директор правит людей, но не заводит зоны
    expect(screen.queryByRole("button", { name: "Новая зона" })).toBeNull();
    const panel = await openZone("Финансы");
    expect(within(panel).queryByRole("button", { name: "Выключить зону" })).toBeNull();
    await chooseOption(
      within(panel).getByRole("combobox", { name: "Ответственный" }),
      "Демо Бухгалтеров",
    );
    fireEvent.change(within(panel).getByRole("textbox", { name: "Основание" }), {
      target: { value: "Приказ № 5 от 01.12.2026" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить" }));

    const row = await rowOf("Финансы");
    await waitFor(() => {
      expect(row).toHaveTextContent("Демо Бухгалтеров");
    });
    expect(row).not.toHaveTextContent("Нет ответственного");
    expect(readZones()[0]).toMatchObject({
      responsibleId: "u-demo-accountant",
      basis: "Приказ № 5 от 01.12.2026",
    });
  });

  it("у ответственного нет разделов зоны — предупреждение, но назначить можно", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/zones");
    await heading();
    const panel = await openZone("Право");
    await chooseOption(
      within(panel).getByRole("combobox", { name: "Ответственный" }),
      "Демо Менеджеров",
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Сохранить" }));
    const row = await rowOf("Право");
    await waitFor(() => {
      expect(row).toHaveTextContent("Нет прав зоны");
    });
    expect(row).toHaveTextContent("Демо Менеджеров");
  });

  it("администратор заводит зону из существующих разделов и выключает её", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/zones");
    await heading();
    fireEvent.click(await screen.findByRole("button", { name: "Новая зона" }));
    const form = await screen.findByRole("region", { name: "Новая зона" });
    fireEvent.change(within(form).getByRole("textbox", { name: "Название по-русски" }), {
      target: { value: "Качество" },
    });
    fireEvent.change(within(form).getByRole("textbox", { name: "Название по-узбекски" }), {
      target: { value: "Sifat" },
    });
    fireEvent.change(within(form).getByRole("textbox", { name: "Название по-английски" }), {
      target: { value: "Quality" },
    });
    // без разделов форма не уходит
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));
    expect(await within(form).findByText("Выберите хотя бы один раздел")).toBeInTheDocument();
    await chooseOption(
      within(form).getByRole("combobox", { name: "Разделы прав зоны" }),
      "Контакты · Контрагенты, создать заявку",
    );
    fireEvent.click(within(form).getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(readZones()).toHaveLength(10);
    });
    const row = await rowOf("Качество");
    expect(row).toHaveTextContent("Нет ответственного");
    expect(readZones().at(-1)).toMatchObject({ code: "quality", sections: ["crm.clients"] });

    const panel = await openZone("Качество");
    fireEvent.click(within(panel).getByRole("button", { name: "Выключить зону" }));
    await waitFor(() => {
      expect(screen.queryByText("Качество", { selector: "b" })).toBeNull();
    });
    fireEvent.click(screen.getByText("Все", { selector: ".ant-segmented-item-label" }));
    expect(await rowOf("Качество")).toHaveTextContent("Выключена");
  });

  it("менеджеру страница недоступна", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/zones");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Нет доступа" }),
    ).toBeInTheDocument();
  });
});

describe("Сигнал «зона без ответственного»", () => {
  it("Настройки: строка со счётом и ссылкой, пока есть зона без ответственного", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin");
    expect(await screen.findByText(/Зон без ответственного: 9\./)).toBeInTheDocument();
    const line = screen.getByText(/Зон без ответственного: 9\./).closest("p") as HTMLElement;
    expect(within(line).getByRole("link", { name: "Открыть" })).toHaveAttribute(
      "href",
      "/admin/zones",
    );
  });

  it("Главная: карточка директору, а менеджеру её нет", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    expect(await screen.findByText("Зоны без ответственного")).toBeInTheDocument();
    cleanup();
    endSession();
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Зоны без ответственного")).toBeNull();
  });
});
