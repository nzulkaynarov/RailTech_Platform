import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetLeads } from "../../../mocks/fixtures/leads";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";

setupBotTests();

beforeEach(() => {
  resetLeads();
});

async function open(email: string, path = "/crm/clients") {
  signIn(email);
  const view = renderAt(path);
  expect(await screen.findByRole("heading", { level: 1, name: "Клиенты" })).toBeVisible();
  return view;
}

describe("Клиенты · Клиенты (D1-2b)", () => {
  it("список с поиском по названию и ИНН; ошибка передачи в бэк-офис — словом", async () => {
    await open("manager@demo.example");
    const table = await screen.findByRole("table", { name: "Клиенты" });
    expect(
      within(table).getByRole("link", { name: "Открыть карточку ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    expect(within(table).getByText("Ошибка передачи")).toBeVisible();

    const search = screen.getByRole("searchbox", { name: "Поиск по названию и ИНН" });
    fireEvent.change(search, { target: { value: "300000003" } });
    fireEvent.keyDown(search, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      expect(
        within(screen.getByRole("table", { name: "Клиенты" })).getAllByRole("row"),
      ).toHaveLength(2);
    });
  });

  it("карточка 360°: контакты с каналами, переписка, заявки со шкалой и тем, что видит клиент, документы, приглашение", async () => {
    await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" }),
    ).toBeVisible();
    expect(within(panel).getByText("ИНН 300000003")).toBeVisible();

    const contacts = within(panel).getByRole("region", { name: "Контакты" });
    expect(within(contacts).getByText("Бобур Снабженцев")).toBeVisible();
    expect(within(contacts).getByText("основной")).toBeVisible();
    expect(within(contacts).getByText("Telegram: @bobur_demo")).toBeVisible();

    const conversation = within(panel).getByRole("region", { name: "Переписка" });
    expect(
      within(conversation).getByRole("link", {
        name: "Бобур Снабженцев · L-2033 — открыть переписку в «Ждут ответа»",
      }),
    ).toHaveAttribute("href", "/crm/messages?lead=L-2033");

    const requests = within(panel).getByRole("region", { name: "Заявки и проекты" });
    expect(within(requests).getByText("ЗВ-2026-031")).toBeVisible();
    expect(within(requests).getByRole("list", { name: "Путь заявки ЗВ-2026-031" })).toBeVisible();
    expect(within(requests).getByText(/Клиент видит: «Ждёт вашего решения»/)).toBeVisible();
    expect(within(requests).getByText(/Клиент видит: «Ожидает оплаты»/)).toBeVisible();

    const docs = within(panel).getByRole("region", { name: "Документы" });
    expect(within(docs).getByText(/Договор поставки/)).toBeVisible();

    const invitation = within(panel).getByRole("region", { name: "Приглашение в кабинет" });
    expect(within(invitation).getByText(/отправлено/)).toBeVisible();
    expect(within(panel).getByRole("link", { name: "Новая заявка для клиента" })).toHaveAttribute(
      "href",
      "/crm/clients?client=3&create=1&panel=open&tab=card",
    );
  });

  it("«Повторить отправку в ERP»: заявка без номера получает номер, кнопка уходит", async () => {
    await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    const panel = await panelEl();
    const requests = await within(panel).findByRole("region", { name: "Заявки и проекты" });
    expect(within(requests).getByText(/Не передана в бэк-офис: бэк-офис не ответил/)).toBeVisible();

    fireEvent.click(
      within(requests).getByRole("button", {
        name: "Повторить отправку в ERP заявки «Заявка: ООО Рельс-Сервис Демо»",
      }),
    );
    await waitFor(() => {
      expect(within(requests).queryByRole("button", { name: /Повторить отправку/ })).toBeNull();
    });
    expect(await within(requests).findByText("ЗВ-2026-040")).toBeVisible();
  });

  it("«Отправить повторно другим каналом»: выбранный канал уходит, итог — словами", async () => {
    await open("manager@demo.example", "/crm/clients/3?panel=open&tab=card");
    const panel = await panelEl();
    const invitation = await within(panel).findByRole("region", { name: "Приглашение в кабинет" });
    fireEvent.click(
      within(invitation).getByRole("button", { name: "Отправить повторно другим каналом" }),
    );
    expect(await within(invitation).findByText("Приглашение отправлено")).toBeVisible();
  });

  it("бухгалтер (клиенты — чтение): карточка без «Новой заявки», «Повторить» и повторного приглашения", async () => {
    await open("accountant@demo.example", "/crm/clients/3?panel=open&tab=card");
    const panel = await panelEl();
    await within(panel).findByRole("heading", { name: "ООО Рельс-Сервис Демо" });
    expect(within(panel).queryByRole("link", { name: "Новая заявка для клиента" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Повторить отправку/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Отправить повторно/ })).toBeNull();
  });
});
