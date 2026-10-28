import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { readLeads, resetLeads } from "../../../mocks/fixtures/leads";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";
import type { RequestFormIn } from "../../../shared/api/generated/model";
import {
  type RequestContext,
  emptyRequestForm,
  toRequestPayload,
  validateRequest,
} from "./formModel";

setupBotTests();

beforeEach(() => {
  resetLeads();
});

async function openForm(path: string): Promise<HTMLElement> {
  signIn("manager@demo.example");
  renderAt(path);
  const panel = await panelEl();
  await within(panel).findByRole("form", { name: "Создать заявку" });
  return panel;
}

function requestsOf(clientName: string): number {
  return readLeads().clients.find((c) => c.name === clientName)?.requests.length ?? 0;
}

describe("форма «Создать заявку»: правила до отправки", () => {
  const lead: RequestContext = {
    lead: "L-2077",
    leadChannel: "phone",
    leadTelegram: null,
    consentGiven: false,
    contacts: [],
  };

  it("пустая форма: компания, контакт, канал, суть и согласие", () => {
    expect(validateRequest(emptyRequestForm(), lead)).toEqual({
      company: "company",
      contact: "contact",
      channel: "channel",
      summary: "summary",
      consent: "consent",
    });
  });

  it("лид из Telegram без согласия — согласие только в боте; неверный ИНН — словами", () => {
    const state = { ...emptyRequestForm(), companyName: "ООО Демо", inn: "12ab", fullName: "Демо" };
    const errors = validateRequest(
      { ...state, useLeadTelegram: true, summary: "Шпалы" },
      { ...lead, leadChannel: "telegram", leadTelegram: "demo" },
    );
    expect(errors).toEqual({ inn: "inn", consent: "consent_via_bot" });
  });

  it("контакт клиента без каналов не подходит", () => {
    const state = { ...emptyRequestForm(), clientId: 4, contactId: 41, summary: "Колодки" };
    const ctx: RequestContext = {
      lead: null,
      leadChannel: null,
      leadTelegram: null,
      consentGiven: true,
      contacts: [
        {
          id: 41,
          name: "Демо",
          position: null,
          phone: null,
          email: null,
          telegram: null,
          channels: [],
          preferred_channel: null,
          is_primary: true,
        },
      ],
    };
    expect(validateRequest(state, ctx)).toEqual({ channel: "contact_channel_required" });
  });

  it("тело запроса: новая компания, новый контакт с Telegram лида, письмо и согласие сотрудника", () => {
    const payload = toRequestPayload(
      {
        ...emptyRequestForm(),
        companyName: " ООО Демо ",
        inn: "",
        fullName: "Демо",
        phone: "+998900000077",
        summary: "Колодки",
        urgency: "urgent",
        letter: { name: "pismo.pdf", status: "done", id: "f-1" },
        consentMarked: true,
        consentMethod: "paper",
      },
      lead,
      "11111111-1111-4111-8111-111111111111",
    );
    expect(payload).toEqual<RequestFormIn>({
      request_key: "11111111-1111-4111-8111-111111111111",
      lead: "L-2077",
      company: { name: "ООО Демо", inn: null },
      contact: {
        full_name: "Демо",
        position: null,
        phone: "+998900000077",
        email: null,
        use_lead_telegram: false,
      },
      summary: "Колодки",
      urgency: "urgent",
      letter_file_id: "f-1",
      consent: { method: "paper", comment: null },
    });
  });
});

describe("«Создать заявку» из лида и из клиента (D1-2b)", () => {
  it("лид «Просит КП»: поля из переписки, письмо директору, «Что произойдёт»; заявка — в карточке клиента", async () => {
    const panel = await openForm("/crm/leads?lead=L-2041&create=1&panel=open&tab=card");
    expect(within(panel).getByLabelText("Название компании")).toHaveValue("ООО Демо-Логистик");
    expect(within(panel).getByLabelText("Имя")).toHaveValue("Азиз Демо");
    expect(
      within(panel).getByRole("checkbox", { name: "Telegram лида (@aziz_demo)" }),
    ).toBeChecked();
    expect(within(panel).getByLabelText("Суть запроса")).toHaveValue("Рельсы Р65, 40 т");

    fireEvent.change(within(panel).getByLabelText("Письмо на имя директора"), {
      target: { files: [new File(["%PDF-1.4"], "pismo.pdf", { type: "application/pdf" })] },
    });
    expect(await within(panel).findByText("Письмо загружено: pismo.pdf")).toBeVisible();
    fireEvent.click(within(panel).getByRole("radio", { name: "Срочная" }));
    const consequence = within(panel).getByRole("group", { name: "Что произойдёт" });
    expect(within(consequence).getByText(/Лид станет клиентом/)).toBeVisible();
    expect(within(consequence).getByText(/с пометкой «Срочно»/)).toBeVisible();

    const submit = within(panel).getByRole("button", { name: /Создать заявку → директору/ });
    // Двойной клик — одна заявка: кнопка занята, а ключ формы тот же
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    expect(requestsOf("ООО Демо-Логистик")).toBe(1);
    const created = readLeads().clients.find((c) => c.name === "ООО Демо-Логистик");
    expect(created?.requests[0]?.letter_file_id).toBeTruthy();
    expect(created?.requests[0]?.urgency).toBe("urgent");
    expect(within(panel).getByRole("link", { name: "Открыть карточку клиента" })).toHaveAttribute(
      "href",
      `/crm/clients/${String(created?.id)}?panel=open&tab=card`,
    );
  });

  it("сбой сервера оставляет введённое; повтор с тем же ключом создаёт одну заявку", async () => {
    const keys: string[] = [];
    server.use(
      http.post(
        "*/api/v1/crm/requests",
        async ({ request }) => {
          keys.push(((await request.clone().json()) as RequestFormIn).request_key);
          return HttpResponse.json(
            { code: "BACKEND_UNAVAILABLE", message: "CRM не отвечает", source: "crm", details: {} },
            { status: 503 },
          );
        },
        { once: true },
      ),
    );
    const panel = await openForm("/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Шпалы, 300 шт, до конца месяца" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(
      await within(panel).findByText(
        "Не удалось создать заявку. Данные формы сохранены — повторите",
      ),
    ).toBeVisible();
    expect(within(panel).getByLabelText("Суть запроса")).toHaveValue(
      "Шпалы, 300 шт, до конца месяца",
    );

    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    expect(keys).toHaveLength(1);
    expect(readLeads().keys[keys[0] ?? ""]).toBeDefined();
    expect(requestsOf("ООО Демо-Строй")).toBe(1);
  });

  it("ошибки у полей: без компании и сути заявка не уходит", async () => {
    const panel = await openForm("/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
    fireEvent.change(within(panel).getByLabelText("Название компании"), { target: { value: "" } });
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), { target: { value: " " } });
    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(
      await within(panel).findByText("Выберите клиента или впишите название компании"),
    ).toBeVisible();
    expect(within(panel).getByText("Опишите суть запроса")).toBeVisible();
    expect(within(panel).getByLabelText("Название компании")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(readLeads().clients.some((c) => c.name === "ООО Демо-Строй")).toBe(false);
  });

  it("лид без согласия (звонок): без отметки — отказ у поля, с отметкой «по телефону» — заявка", async () => {
    const panel = await openForm("/crm/leads?lead=L-2077&create=1&panel=open&tab=card");
    expect(within(panel).getByText("Клиент ещё не дал согласие.")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(await within(panel).findByText("Без согласия клиента заявку не создать")).toBeVisible();

    fireEvent.click(within(panel).getByRole("checkbox", { name: "Согласие получено" }));
    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
  });

  it("из карточки клиента: основной контакт по умолчанию, заявка добавляется к клиенту", async () => {
    const before = requestsOf("ООО Рельс-Сервис Демо");
    const panel = await openForm("/crm/clients?client=3&create=1&panel=open&tab=card");
    expect(await within(panel).findByText("Клиент: ООО Рельс-Сервис Демо")).toBeVisible();
    expect(within(panel).queryByLabelText("Название компании")).toBeNull();
    expect(within(panel).queryByRole("group", { name: "Согласие на обработку данных" })).toBeNull();
    await waitFor(() => {
      expect(within(panel).getByText(/^Бобур Снабженцев.* — Telegram/)).toBeVisible();
    });
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Накладки рельсовые" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: /Создать заявку → директору/ }));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    expect(requestsOf("ООО Рельс-Сервис Демо")).toBe(before + 1);
  });
});

describe("«Создать заявку» на телефоне", () => {
  it("390: форма — лист на весь экран, кнопки внизу", async () => {
    setViewportWidth(390);
    signIn("manager@demo.example");
    renderAt("/crm/leads?lead=L-2041&create=1");
    const sheet = await screen.findByRole("dialog", { name: "Создать заявку" });
    const form = await within(sheet).findByRole("form", { name: "Создать заявку" });
    const actions = form.querySelector(".pf-crm-actions");
    expect(actions).toHaveAttribute("data-sheet", "true");
    expect(within(sheet).getByRole("button", { name: "Отмена" })).toBeVisible();
  });
});
