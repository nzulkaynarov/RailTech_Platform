import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { readLeads, resetLeads, writeLeads } from "../../../mocks/fixtures/leads";
import { resetMessages } from "../../../mocks/fixtures/messages";
import { panelEl, renderAt, setupBotTests, signIn } from "../../../test/botKit";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";
import type { Me, RequestFormIn } from "../../../shared/api/generated/model";
import { canCreateFromLead } from "../common/access";
import { requestDraftScope } from "./draft";
import {
  type RequestContext,
  emptyRequestForm,
  toRequestPayload,
  validateRequest,
} from "./formModel";

setupBotTests();

beforeEach(() => {
  resetLeads();
  resetMessages();
});

async function openForm(path: string): Promise<HTMLElement> {
  signIn("manager@demo.example");
  renderAt(path);
  const panel = await panelEl();
  await within(panel).findByRole("form", { name: "Создать заявку" });
  return panel;
}

/** Открыть секцию формы (секции по шагам, platform-frontend.md §4.1a), если она свёрнута. */
function open(panel: HTMLElement, title: string): void {
  const head = within(panel).queryByRole("button", {
    name: new RegExp(`^${title}`),
    expanded: false,
  });
  if (head) fireEvent.click(head);
}

/** «Создать заявку» — в последней секции «Проверка и отправка». */
function submitButton(panel: HTMLElement): HTMLElement {
  open(panel, "Проверка и отправка");
  return within(panel).getByRole("button", { name: /Создать заявку/ });
}

/** Основание заявки (план 0.4): письмо или файл запроса в секции «Запрос». */
async function attach(panel: HTMLElement, name = "pismo.pdf"): Promise<void> {
  open(panel, "Запрос");
  fireEvent.change(within(panel).getByLabelText("Письмо или файл запроса"), {
    target: { files: [new File(["%PDF-1.4"], name, { type: "application/pdf" })] },
  });
  expect(await within(panel).findByText(`Загружено: ${name}`)).toBeVisible();
}

/** Заголовок шага (кнопка раскрытия), а не ссылка с тем же словом в списке «Осталось». */
function stepHead(panel: HTMLElement, title: string): HTMLElement {
  const head = within(panel)
    .getAllByRole("button", { name: new RegExp(`^${title}`) })
    .find((button) => button.hasAttribute("aria-controls"));
  if (!head) throw new Error(`нет шага ${title}`);
  return head;
}

/** Список «Осталось» на шаге «Проверка и отправка» — причина, по которой «Создать заявку» недоступна. */
function remainingList(panel: HTMLElement): HTMLElement {
  const list = panel.querySelector<HTMLElement>(".pf-fstep-remaining");
  if (!list) throw new Error("нет списка «Осталось»");
  return list;
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

  it("пустая форма: компания, контакт, канал, суть, основание и согласие", () => {
    expect(validateRequest(emptyRequestForm(), lead)).toEqual({
      company: "company",
      contact: "contact",
      channel: "channel",
      summary: "summary",
      letter: "letter_call_consent",
      consent: "consent",
    });
    // Телефонный лид с согласием: основание — записка или файл, текст обычный.
    expect(validateRequest({ ...emptyRequestForm(), consentMarked: true }, lead).letter).toBe(
      "letter_required",
    );
  });

  it("лид из Telegram без согласия — согласие только в боте; неверный ИНН — словами", () => {
    const state = {
      ...emptyRequestForm(),
      companyName: "ООО Демо",
      inn: "12ab",
      fullName: "Демо",
      letter: { name: "pismo.pdf", status: "done" as const, id: "f-1" },
    };
    const errors = validateRequest(
      { ...state, useLeadTelegram: true, summary: "Шпалы" },
      { ...lead, leadChannel: "telegram", leadTelegram: "demo" },
    );
    expect(errors).toEqual({ inn: "inn", consent: "consent_via_bot" });
  });

  it("контакт клиента без каналов не подходит", () => {
    const state = {
      ...emptyRequestForm(),
      clientId: 4,
      contactId: 41,
      summary: "Колодки",
      letter: { name: "pismo.pdf", status: "done" as const, id: "f-1" },
    };
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
    open(panel, "Контакт");
    expect(within(panel).getByLabelText("Имя")).toHaveValue("Азиз Демо");
    expect(
      within(panel).getByRole("checkbox", { name: "Telegram лида (@aziz_demo)" }),
    ).toBeChecked();
    open(panel, "Запрос");
    expect(within(panel).getByLabelText("Суть запроса")).toHaveValue("Рельсы Р65, 40 т");

    await attach(panel);
    fireEvent.click(within(panel).getByRole("radio", { name: "Срочная" }));

    const submit = submitButton(panel);
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
    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Шпалы, 300 шт, до конца месяца" },
    });
    await attach(panel);
    fireEvent.click(submitButton(panel));
    expect(
      await within(panel).findByText(
        "Не удалось создать заявку. Данные формы сохранены — повторите",
      ),
    ).toBeVisible();
    expect(within(panel).getByLabelText("Суть запроса")).toHaveValue(
      "Шпалы, 300 шт, до конца месяца",
    );

    // Текст ошибки появляется раньше, чем AntD снимает с кнопки «загрузку» (отдельная перерисовка после ответа),
    // а клик по кнопке в загрузке AntD игнорирует: на загруженном раннере CI повтор терялся.
    const submit = submitButton(panel);
    await waitFor(() => {
      expect(submit).not.toHaveClass("ant-btn-loading");
    });
    fireEvent.click(submit);
    // Повтор идёт после ответа 503 и полной перерисовки формы: на загруженном раннере CI это дольше
    // секунды по умолчанию у findBy*.
    expect(
      await within(panel).findByText("Заявка создана", undefined, { timeout: 5000 }),
    ).toBeVisible();
    expect(keys).toHaveLength(1);
    expect(readLeads().keys[keys[0] ?? ""]).toBeDefined();
    expect(requestsOf("ООО Демо-Строй")).toBe(1);
  });

  it("шаг готов по тому же валидатору: требования видны на шаге после ухода с него, «Осталось» — на проверке, кнопка недоступна", async () => {
    const panel = await openForm("/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
    fireEvent.change(within(panel).getByLabelText("Название компании"), { target: { value: "" } });
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), { target: { value: " " } });
    // пока с шага не уходили, он не пестрит требованиями
    expect(within(panel).queryByText("Чтобы шаг был готов:")).toBeNull();
    open(panel, "Запрос");
    // «Клиент» покинут с невыполненным: отметка у заголовка, требование на самом шаге, поле помечено
    expect(within(panel).getByRole("button", { name: /^Клиент.*нужно исправить/i })).toBeVisible();
    expect(within(panel).getByLabelText("Название компании")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    // шаг «Запрос» открыт впервые: его требования не показаны, галочки у него нет
    expect(within(panel).queryByText("Опишите суть запроса")).toBeNull();

    const submit = submitButton(panel);
    expect(submit).toBeDisabled();
    const list = remainingList(panel);
    expect(within(list).getByText(/Выберите клиента или впишите название компании/)).toBeVisible();
    expect(within(list).getByText(/Опишите суть запроса/)).toBeVisible();
    expect(within(list).getByText(/Приложите письмо клиента или файл запроса/)).toBeVisible();
    expect(submit).toHaveAttribute("aria-describedby", list.id);
    // ссылка из списка ведёт на шаг, где это исправить
    fireEvent.click(within(list).getByRole("button", { name: "Клиент" }));
    expect(within(panel).getByLabelText("Название компании")).toBeVisible();
    expect(readLeads().clients.some((c) => c.name === "ООО Демо-Строй")).toBe(false);
  });

  it("шаг с выполненным ставит галочку только тем же валидатором: «Запрос» без файла и «Контакт» без согласия не готовы", async () => {
    const panel = await openForm("/crm/leads?lead=L-2077&create=1&panel=open&tab=card");
    open(panel, "Контакт");
    open(panel, "Запрос");
    open(panel, "Проверка и отправка");
    // суть из лида есть, но основания нет — шаг «Запрос» не получил галочку и показывает требование
    expect(stepHead(panel, "Запрос")).toHaveTextContent(/нужно исправить/i);
    // согласия нет — то же у «Контакта»
    expect(stepHead(panel, "Контакт")).toHaveTextContent(/нужно исправить/i);
    expect(within(panel).getByRole("button", { name: "Создать заявку" })).toBeDisabled();
  });

  it("лид без согласия (звонок): согласие — на шаге «Контакт»; без отметки кнопка недоступна, с отметкой «по телефону» — заявка", async () => {
    const panel = await openForm("/crm/leads?lead=L-2077&create=1&panel=open&tab=card");
    open(panel, "Контакт");
    expect(within(panel).getByText("Клиент ещё не дал согласие.")).toBeVisible();
    await attach(panel);
    // в «Запросе» согласия больше нет
    open(panel, "Запрос");
    expect(within(panel).queryByText("Клиент ещё не дал согласие.")).not.toBeVisible();

    const blocked = submitButton(panel);
    expect(blocked).toBeDisabled();
    expect(
      within(remainingList(panel)).getByText(/Без согласия клиента заявку не создать/),
    ).toBeVisible();

    open(panel, "Контакт");
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Согласие получено" }));
    const submit = submitButton(panel);
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
  });

  it("из карточки клиента: основной контакт по умолчанию, заявка добавляется к клиенту", async () => {
    const before = requestsOf("ООО Рельс-Сервис Демо");
    const panel = await openForm("/crm/clients?client=3&create=1&panel=open&tab=card");
    // клиент уже выбран: форма открыта на «Контакте», клиент — в строке итога первой секции
    expect(
      await within(panel).findByRole("button", { name: /^Клиент.*ООО Рельс-Сервис Демо/ }),
    ).toBeVisible();
    expect(within(panel).queryByLabelText("Название компании")).toBeNull();
    expect(within(panel).queryByRole("group", { name: "Согласие на обработку данных" })).toBeNull();
    await waitFor(() => {
      expect(within(panel).getByText(/^Бобур Снабженцев.* — Telegram/)).toBeVisible();
    });
    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Накладки рельсовые" },
    });
    await attach(panel);
    fireEvent.click(submitButton(panel));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    expect(requestsOf("ООО Рельс-Сервис Демо")).toBe(before + 1);
  });
});

describe("письмо директору: из переписки и при сбое загрузки", () => {
  it("«В заявку» у файла клиента в «Ждут ответа» — форма с этим файлом как письмом директору", async () => {
    signIn("manager@demo.example");
    const { router } = renderAt("/crm/messages?lead=L-2041");
    const button = await screen.findByRole(
      "link",
      { name: "В заявку: Заявка-демо.pdf — письмом директору" },
      { timeout: 10_000 },
    );
    fireEvent.click(button);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/crm/leads");
    });
    const panel = await panelEl();
    await within(panel).findByRole("form", { name: "Создать заявку" });
    open(panel, "Запрос");
    expect(await within(panel).findByText("Загружено: письмо-директору.pdf")).toBeVisible();
    fireEvent.click(submitButton(panel));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    const created = readLeads().clients.find((c) => c.name === "ООО Демо-Логистик");
    expect(created?.requests[0]?.letter_file_id).toBeTruthy();
  });

  it("чужой лид по адресу `create=1`: формы нет, вложение в EDS не копируется", async () => {
    const state = readLeads();
    const other = { id: "u-other", name: "Другой Менеджер", initials: "ДМ" };
    const lead = state.leads.find((l) => l.row.lead === "L-2041");
    if (!lead) throw new Error("нет L-2041");
    lead.row.assigned = other;
    lead.card.assigned = other;
    writeLeads(state);
    let copies = 0;
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/crm/request-files/from-message")) copies += 1;
    });
    signIn("manager@demo.example");
    renderAt("/crm/leads?lead=L-2041&create=1&letter=2041000-0&panel=open&tab=card");
    const panel = await panelEl();
    expect(await within(panel).findByText("Лида ведёт другой сотрудник")).toBeVisible();
    expect(within(panel).queryByRole("form", { name: "Создать заявку" })).toBeNull();
    expect(copies).toBe(0);
    server.events.removeAllListeners();
  });

  it("без основания и со сбоем загрузки заявка не уходит (план 0.4, FR-9)", async () => {
    const panel = await openForm("/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
    expect(submitButton(panel)).toBeDisabled();
    expect(
      within(remainingList(panel)).getByText(/Приложите письмо клиента или файл запроса/),
    ).toBeVisible();
    expect(requestsOf("ООО Демо-Строй")).toBe(0);

    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Письмо или файл запроса"), {
      target: { files: [new File(["MZ"], "virus.exe", { type: "application/x-msdownload" })] },
    });
    expect(
      await within(panel).findByText("Подходит PDF, изображение или документ Office"),
    ).toBeVisible();
    expect(submitButton(panel)).toBeDisabled();
    expect(within(remainingList(panel)).getByText(/Файл не загрузился — выберите/)).toBeVisible();
    expect(requestsOf("ООО Демо-Строй")).toBe(0);

    open(panel, "Запрос");
    fireEvent.click(within(panel).getByRole("button", { name: "Убрать файл" }));
    await attach(panel, "zapros.pdf");
    fireEvent.click(submitButton(panel));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
  });
});

describe("черновик заявки и лид из Telegram без согласия (СЦ-6)", () => {
  const PATH = "/crm/leads?lead=L-2044&create=1&panel=open&tab=card";

  it("закрыли форму — при открытии «Продолжить / Начать заново»; молча ничего не подставляется; ключ формы и файл те же", async () => {
    const panel = await openForm(PATH);
    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Шпалы, 300 шт, до конца месяца" },
    });
    await attach(panel, "zapros.pdf");
    const stored = window.sessionStorage.getItem(
      Object.keys(window.sessionStorage).find((k) => k.includes("request-draft")) ?? "",
    );
    const draftKey = (JSON.parse(stored ?? "{}") as { requestKey?: string }).requestKey;
    expect(draftKey).toBeTruthy();

    cleanup();
    const again = await openForm(PATH);
    expect(within(again).getByText(/Есть черновик заявки от/)).toBeVisible();
    open(again, "Запрос");
    expect(within(again).getByLabelText("Суть запроса")).not.toHaveValue(
      "Шпалы, 300 шт, до конца месяца",
    );

    fireEvent.click(within(again).getByRole("button", { name: "Продолжить" }));
    expect(within(again).queryByText(/Есть черновик заявки от/)).toBeNull();
    expect(within(again).getByLabelText("Суть запроса")).toHaveValue(
      "Шпалы, 300 шт, до конца месяца",
    );
    expect(within(again).getByText("Загружено: zapros.pdf")).toBeVisible();
    fireEvent.click(submitButton(again));
    expect(await within(again).findByText("Заявка создана")).toBeVisible();
    // ключ из черновика: повтор после потерянного ответа вернёт ту же заявку; созданная заявка стирает черновик
    expect(Object.keys(readLeads().keys)).toContain(draftKey);
    expect(Object.keys(window.sessionStorage).some((k) => k.includes("request-draft"))).toBe(false);
  });

  it("«Начать заново» стирает черновик, форма — с данными лида", async () => {
    const panel = await openForm(PATH);
    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), { target: { value: "Другое" } });
    cleanup();
    const again = await openForm(PATH);
    fireEvent.click(within(again).getByRole("button", { name: "Начать заново" }));
    expect(within(again).queryByText(/Есть черновик заявки от/)).toBeNull();
    open(again, "Запрос");
    expect(within(again).getByLabelText("Суть запроса")).not.toHaveValue("Другое");
    cleanup();
    const third = await openForm(PATH);
    // форму не меняли — черновика нет
    expect(within(third).queryByText(/Есть черновик заявки от/)).toBeNull();
  });

  it("лид из Telegram без согласия: вместо формы причина — отметить согласие здесь нельзя", async () => {
    const state = readLeads();
    const lead = state.leads.find((l) => l.row.lead === "L-2041");
    if (!lead) throw new Error("нет L-2041");
    lead.card.consent = { given_at: null, method: null };
    writeLeads(state);
    signIn("manager@demo.example");
    renderAt("/crm/leads?lead=L-2041&create=1&panel=open&tab=card");
    const panel = await panelEl();
    expect(await within(panel).findByText(/Лид из Telegram даёт согласие в боте/)).toBeVisible();
    expect(within(panel).queryByRole("form", { name: "Создать заявку" })).toBeNull();
  });
});

describe("кнопка «Создать заявку» у чужого лида", () => {
  const me = (resources: Record<string, "full" | "read">) =>
    ({ id: "7", resources }) as unknown as Me;
  const other = { id: "9", name: "Другой Менеджер", initials: "ДМ" };
  const self = { id: "7", name: "Я", initials: "Я" };

  it("свободный и свой лид — можно; чужой — нет (CRM ответит not_lead_owner); администратору — можно; без права на клиентов — нет", () => {
    const manager = me({ "crm.clients": "full" });
    expect(canCreateFromLead(manager, null)).toBe(true);
    expect(canCreateFromLead(manager, self)).toBe(true);
    expect(canCreateFromLead(manager, other)).toBe(false);
    expect(canCreateFromLead(me({ "crm.clients": "full", admin: "full" }), other)).toBe(true);
    expect(canCreateFromLead(me({ "crm.clients": "read" }), null)).toBe(false);
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
    open(sheet, "Проверка и отправка");
    expect(within(sheet).getByRole("button", { name: "Отмена" })).toBeVisible();
  });
});

describe("ключ черновика заявки по месту открытия (СЦ-6)", () => {
  it("форма из входящего с файлом ВХ ведёт свой черновик, не общий «new» из «Создать → Заявка»", () => {
    expect(requestDraftScope(null, null)).toBe("new");
    expect(requestDraftScope(null, null, "doc-7")).toBe("letter:doc-7");
    expect(requestDraftScope(null, null, "doc-7")).not.toBe(requestDraftScope(null, null));
    expect(requestDraftScope("L-2044", null)).toBe("L-2044");
    expect(requestDraftScope(null, 5)).toBe("client:5");
  });
});

describe("записка о звонке как основание заявки (СЦ-6)", () => {
  const PHONE = "/crm/leads?lead=L-2077&create=1&panel=open&tab=card";
  const NOTE_URL = "*/api/v1/crm/request-files/call-note";

  /** Тела заказов записки: сколько раз форма заказывала её и с чем. */
  function recordNotes(): { bodies: Record<string, unknown>[] } {
    const seen: { bodies: Record<string, unknown>[] } = { bodies: [] };
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/crm/request-files/call-note")) {
        void request
          .clone()
          .json()
          .then((body: Record<string, unknown>) => seen.bodies.push(body));
      }
    });
    return seen;
  }

  function markConsent(panel: HTMLElement): void {
    open(panel, "Контакт");
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Согласие получено" }));
  }

  it("лид со звонка и согласием: записка собирается сама на шаге «Запрос», файл не нужен, заявка уходит с её id", async () => {
    const notes = recordNotes();
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    expect(within(panel).getByRole("button", { name: /^Открыть/ })).toBeVisible();
    expect(within(panel).getByText("Заменить файлом")).toBeVisible();
    await waitFor(() => {
      expect(notes.bodies).toHaveLength(1);
    });
    expect(notes.bodies[0]).toMatchObject({ lead: "L-2077", consent: true, lang: "ru" });

    const submit = submitButton(panel);
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    const created = readLeads().clients.find((c) => c.name === "ООО Демо-Депо");
    expect(created?.requests[0]?.letter_file_id).toBeTruthy();
    server.events.removeAllListeners();
  });

  it("без согласия записка не собирается: кнопка недоступна, причина видна, «Осталось» ведёт к согласию", async () => {
    const notes = recordNotes();
    const panel = await openForm(PHONE);
    open(panel, "Запрос");
    expect(within(panel).queryByText("Записка о звонке приложена")).toBeNull();
    expect(within(panel).getByRole("button", { name: "Основание — звонок" })).toBeDisabled();
    expect(
      within(panel).getByText(
        "Записка о звонке соберётся, когда на шаге «Контакт» отмечено согласие",
      ),
    ).toBeVisible();
    open(panel, "Проверка и отправка");
    expect(
      within(panel).getAllByText(
        "Отметьте согласие на шаге «Контакт» — записка о звонке соберётся сама, или приложите файл",
      ).length,
    ).toBeGreaterThan(0);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(notes.bodies).toHaveLength(0);
    server.events.removeAllListeners();
  });

  it("лид не со звонка: записки и кнопки «Основание — звонок» нет, основание — файл", async () => {
    const notes = recordNotes();
    const panel = await openForm("/crm/leads?lead=L-2044&create=1&panel=open&tab=card");
    open(panel, "Запрос");
    expect(within(panel).queryByRole("button", { name: "Основание — звонок" })).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(notes.bodies).toHaveLength(0);
    server.events.removeAllListeners();
  });

  it("без лида (повторный звонок клиента): записка — по кнопке «Основание — звонок» из полей формы", async () => {
    server.events.removeAllListeners();
    const notes = recordNotes();
    const panel = await openForm("/crm/clients?client=3&create=1&panel=open&tab=card");
    await waitFor(() => {
      expect(within(panel).getByText(/^Бобур Снабженцев.* — Telegram/)).toBeVisible();
    });
    open(panel, "Запрос");
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Повторный заказ накладок" },
    });
    // сама записка без лида не собирается
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(notes.bodies).toHaveLength(0);

    fireEvent.click(within(panel).getByRole("button", { name: "Основание — звонок" }));
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    expect(notes.bodies).toHaveLength(1);
    expect(notes.bodies[0]).toMatchObject({
      caller: { name: "Бобур Снабженцев", company: "ООО Рельс-Сервис Демо" },
      need: "Повторный заказ накладок",
    });
    expect(notes.bodies[0]).not.toHaveProperty("lead");
    fireEvent.click(submitButton(panel));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
    server.events.removeAllListeners();
  });

  it("нет бланка у компании: причина и «приложите файл»; загруженный файл заменяет записку, заявка уходит", async () => {
    server.use(
      http.post(NOTE_URL, () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Бланк",
            source: "eds",
            details: { reason: "letterhead_missing" },
          },
          { status: 409 },
        ),
      ),
    );
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(
      await within(panel).findByText(
        "Записку о звонке не собрать: в компании не настроен бланк. Приложите файл.",
      ),
    ).toBeVisible();
    expect(submitButton(panel)).toBeDisabled();
    await attach(panel, "zapros.pdf");
    expect(within(panel).queryByText("Записка о звонке приложена")).toBeNull();
    fireEvent.click(submitButton(panel));
    expect(await within(panel).findByText("Заявка создана")).toBeVisible();
  });

  it("записка строится в воркере: «Собираем…», затем опрос до готовности", async () => {
    const id = "50000000-0000-4000-8000-000000000001";
    const file = {
      id: "60000000-0000-4000-8000-000000000001",
      name: "Записка.pdf",
      content_type: "application/pdf",
      size: 10,
    };
    let polls = 0;
    server.use(
      http.post(NOTE_URL, () =>
        HttpResponse.json({ id, status: "pending", error: null, file: null }, { status: 202 }),
      ),
      http.get(`${NOTE_URL}/${id}`, () => {
        polls += 1;
        return HttpResponse.json({ id, status: "ready", error: null, file });
      }),
    );
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Собираем записку о звонке…")).toBeVisible();
    expect(submitButton(panel)).toBeDisabled();
    open(panel, "Запрос");
    expect(
      await within(panel).findByText("Записка о звонке приложена", undefined, { timeout: 4000 }),
    ).toBeVisible();
    expect(polls).toBe(1);
    open(panel, "Проверка и отправка");
    expect(submitButton(panel)).toBeEnabled();
  });

  it("«Убрать файл» не пускает автосборку второй раз: записку можно вернуть кнопкой", async () => {
    const notes = recordNotes();
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Убрать файл" }));
    const again = await within(panel).findByRole("button", { name: "Основание — звонок" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(notes.bodies).toHaveLength(1);
    fireEvent.click(again);
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    expect(notes.bodies).toHaveLength(2);
    server.events.removeAllListeners();
  });

  it("черновик хранит записку: после «Продолжить» она приложена и заново не заказывается", async () => {
    const notes = recordNotes();
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    fireEvent.change(within(panel).getByLabelText("Суть запроса"), {
      target: { value: "Колодки" },
    });
    cleanup();

    const again = await openForm(PHONE);
    fireEvent.click(within(again).getByRole("button", { name: "Продолжить" }));
    open(again, "Запрос");
    expect(within(again).getByText("Записка о звонке приложена")).toBeVisible();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(notes.bodies).toHaveLength(1);
    server.events.removeAllListeners();
  });

  it("файл, выбранный во время сборки записки, готовая записка не затирает", async () => {
    const id = "50000000-0000-4000-8000-000000000001";
    server.use(
      http.post(NOTE_URL, () =>
        HttpResponse.json({ id, status: "pending", error: null, file: null }, { status: 202 }),
      ),
      http.get(`${NOTE_URL}/${id}`, () =>
        HttpResponse.json({
          id,
          status: "ready",
          error: null,
          file: {
            id: "60000000-0000-4000-8000-000000000001",
            name: "Записка.pdf",
            content_type: "application/pdf",
            size: 10,
          },
        }),
      ),
    );
    const panel = await openForm(PHONE);
    markConsent(panel);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Собираем записку о звонке…")).toBeVisible();
    await attach(panel, "pismo.pdf");
    await new Promise((resolve) => setTimeout(resolve, 1600));
    expect(within(panel).getByText("Загружено: pismo.pdf")).toBeVisible();
    expect(within(panel).queryByText("Записка о звонке приложена")).toBeNull();
  });

  it("без лида: пока не заполнена суть, записку не собрать; правка после сборки — новая записка с новым ключом", async () => {
    server.events.removeAllListeners();
    const notes = recordNotes();
    const panel = await openForm("/crm/clients?client=3&create=1&panel=open&tab=card");
    await waitFor(() => {
      expect(within(panel).getByText(/^Бобур Снабженцев.* — Telegram/)).toBeVisible();
    });
    open(panel, "Запрос");
    const button = within(panel).getByRole("button", { name: "Основание — звонок" });
    expect(button).toBeDisabled();
    expect(within(panel).getByText("Сначала заполните «Суть запроса»")).toBeVisible();

    const need = within(panel).getByLabelText("Суть запроса");
    fireEvent.change(need, { target: { value: "Накладки" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Основание — звонок" }));
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Убрать файл" }));
    fireEvent.change(need, { target: { value: "Накладки и болты" } });
    fireEvent.click(await within(panel).findByRole("button", { name: "Основание — звонок" }));
    await waitFor(() => {
      expect(notes.bodies).toHaveLength(2);
    });
    expect(notes.bodies[1]).toMatchObject({ need: "Накладки и болты" });
    expect(notes.bodies[1]?.["request_key"]).not.toBe(notes.bodies[0]?.["request_key"]);
    server.events.removeAllListeners();
  });

  it("форма без правки черновиком не становится: записка, собранная системой, «Продолжить» не вызывает", async () => {
    const state = readLeads();
    const lead = state.leads.find((l) => l.row.lead === "L-2077");
    if (!lead) throw new Error("нет L-2077");
    lead.card.consent = { given_at: "2026-10-27T08:00:00Z", method: "phone" };
    writeLeads(state);
    const panel = await openForm(PHONE);
    open(panel, "Запрос");
    expect(await within(panel).findByText("Записка о звонке приложена")).toBeVisible();
    cleanup();
    const again = await openForm(PHONE);
    expect(within(again).queryByText(/Есть черновик заявки от/)).toBeNull();
  });
});
