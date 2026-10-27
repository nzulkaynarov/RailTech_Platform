import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  MOCK_INBOX_EMPTY_KEY,
  MOCK_TELEGRAM_DOWN_KEY,
  readMessages,
  resetMessages,
  writeMessages,
} from "../../../mocks/fixtures/messages";
import { invalidateTopics } from "../../../shared/api/useEventStream";
import { renderAt, setupBotTests, signIn } from "../../../test/botKit";
import i18n from "../../../shared/i18n";
import { ApiError } from "../../../shared/api/errors";
import { sendFailure } from "./labels";
import { mergeThread } from "./logic";
import { durationParts, slaState } from "./sla";
import { SlaTimer } from "./SlaTimer";

setupBotTests();

beforeEach(() => {
  resetMessages();
});

async function open(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/crm/messages${search}`);
  expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
  return view;
}

function field(): HTMLTextAreaElement {
  return screen.getByLabelText<HTMLTextAreaElement>(/Сообщение клиенту|Заметка для команды/);
}

describe("таймер SLA", () => {
  const now = Date.parse("2026-10-27T09:12:00Z");

  it("считает минуты от передачи и краснеет после срока", () => {
    expect(
      slaState({ created_at: "2026-10-27T09:00:00Z", sla_due_at: "2026-10-27T09:15:00Z" }, now),
    ).toEqual({
      minutes: 12,
      overdue: false,
    });
    expect(
      slaState({ created_at: "2026-10-27T08:00:00Z", sla_due_at: "2026-10-27T09:00:00Z" }, now),
    ).toEqual({
      minutes: 72,
      overdue: true,
    });
    expect(slaState({ created_at: "2026-10-27T09:00:00Z", sla_due_at: null }, now).overdue).toBe(
      false,
    );
    expect(durationParts(125)).toEqual({ key: "hours", values: { h: 2, m: 5 } });
    expect(durationParts(60 * 26)).toEqual({ key: "days", values: { d: 1, h: 2 } });
  });

  it("«ждёт 12 мин»; после срока — словами «срок прошёл», не только цветом", () => {
    void i18n.changeLanguage("ru");
    const base = {
      priority: "hot" as const,
      state: "open" as const,
      reasons: [],
      reason_text: null,
      recommendation: null,
      snoozed_until: null,
      taken_by: null,
    };
    const { rerender } = render(
      <SlaTimer
        handoff={{
          ...base,
          created_at: "2026-10-27T09:00:00Z",
          sla_due_at: "2026-10-27T09:15:00Z",
        }}
        now={now}
      />,
    );
    expect(screen.getByText("ждёт 12 мин")).toHaveAttribute("data-overdue", "false");
    rerender(
      <SlaTimer
        handoff={{
          ...base,
          created_at: "2026-10-27T08:30:00Z",
          sla_due_at: "2026-10-27T09:00:00Z",
        }}
        now={now}
      />,
    );
    expect(screen.getByText("ждёт 42 мин · срок прошёл")).toHaveAttribute("data-overdue", "true");
  });
});

describe("Клиенты · Ждут ответа: менеджер", () => {
  it("очередь по группам с запиской и таймером; «Забрать» передаёт лида менеджеру", async () => {
    await open("manager@demo.example");
    const nav = await screen.findByRole("navigation", { name: "Диалоги, которые ждут ответа" });
    expect(within(nav).getByRole("heading", { name: "Передачи от бота · 2" })).toBeVisible();
    expect(within(nav).getByRole("heading", { name: "Мои диалоги · 1" })).toBeVisible();
    expect(within(nav).getByText("ждёт 12 мин")).toBeVisible();
    expect(within(nav).getByText("ждёт 40 мин · срок прошёл")).toBeVisible();
    expect(within(nav).getAllByText("Срочно")[0]).toBeVisible();

    fireEvent.click(within(nav).getByRole("button", { name: "Забрать: Азиз Демо" }));
    expect(await screen.findByText("Лид у вас. Бот молчит, пока вы в диалоге.")).toBeVisible();
    await waitFor(() => {
      expect(readMessages().leads[0]?.card.owner_mode).toBe("manager");
    });
  });

  it("диалог: записка передачи, лента с вложением, подпись «Уйдёт клиенту в Telegram» и заметка команде", async () => {
    await open("manager@demo.example", "?lead=L-2050");
    expect(await screen.findByRole("heading", { level: 2, name: "Тимур Образцов" })).toBeVisible();
    expect(
      await screen.findByText("Счёт пришлёте сегодня?", { selector: ".pf-msg-bubble" }),
    ).toBeVisible();
    expect(screen.getByText("Клиент платит после поставки — уточнить у бухгалтера")).toBeVisible();
    expect(screen.getByText("Уйдёт клиенту в Telegram")).toBeVisible();

    fireEvent.click(screen.getByText("Заметка команде", { selector: ".ant-segmented-item-label" }));
    expect(screen.getByText("Увидит только команда")).toBeVisible();
    fireEvent.change(field(), { target: { value: "Перезвонить после обеда" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить заметку" }));
    expect(
      await screen.findByText("Перезвонить после обеда", { selector: ".pf-msg-bubble" }),
    ).toBeVisible();
    expect(field().value).toBe("");
  });

  it("Telegram не ответил: текст остаётся в поле, «Повторить» шлёт тот же ключ и не дублирует сообщение", async () => {
    await open("manager@demo.example", "?lead=L-2050");
    await screen.findByRole("heading", { level: 2, name: "Тимур Образцов" });
    window.localStorage.setItem(MOCK_TELEGRAM_DOWN_KEY, "1");
    fireEvent.change(field(), { target: { value: "Счёт пришлю до 17:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Не отправлено: Telegram не ответил.")).toBeVisible();
    expect(field().value).toBe("Счёт пришлю до 17:00");
    const before = readMessages().leads.find((l) => l.item.lead === "L-2050")?.messages.length ?? 0;

    window.localStorage.removeItem(MOCK_TELEGRAM_DOWN_KEY);
    fireEvent.click(within(alert).getByRole("button", { name: "Повторить" }));
    await waitFor(() => {
      expect(Object.keys(readMessages().sent)).toHaveLength(1);
    });
    expect(
      await screen.findByText("Счёт пришлю до 17:00", { selector: ".pf-msg-bubble" }),
    ).toBeVisible();
    const state = readMessages();
    expect(state.leads.find((l) => l.item.lead === "L-2050")?.messages.length).toBe(before + 1);
    expect(Object.keys(state.sent)).toHaveLength(1);
    expect(field().value).toBe("");
  });

  it("шаблон и «Подсказать ответ» вставляют текст в поле, отправляет человек", async () => {
    await open("manager@demo.example", "?lead=L-2050");
    await screen.findByRole("heading", { level: 2, name: "Тимур Образцов" });
    fireEvent.click(screen.getByRole("button", { name: "Подсказать ответ" }));
    await waitFor(() => {
      expect(field().value).toContain("Подготовлю коммерческое предложение");
    });
    expect(screen.getByText("Подсказка в поле — проверьте и отправьте сами")).toBeVisible();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Шаблон ответа" }));
    fireEvent.click(
      await screen.findByText("Пришлю КП сегодня", { selector: ".ant-select-item-option-content" }),
    );
    expect(field().value).toBe(
      "Тимур Образцов, добрый день! Пришлю коммерческое предложение сегодня до конца дня. Демо Менеджеров",
    );
  });

  it("подсказка потока `messages` перечитывает открытую ленту без опроса", async () => {
    const { queryClient } = await open("manager@demo.example", "?lead=L-2050");
    await screen.findByRole("heading", { level: 2, name: "Тимур Образцов" });
    const state = readMessages();
    const row = state.leads.find((l) => l.item.lead === "L-2050");
    row?.messages.push({
      id: 999_001,
      author: "lead",
      author_name: null,
      text: "Новое сообщение клиента из бота",
      created_at: new Date().toISOString(),
      attachments: [],
    });
    writeMessages(state);
    expect(screen.queryByText("Новое сообщение клиента из бота")).toBeNull();

    invalidateTopics(queryClient, ["counters", "queue", "messages"]);
    expect(
      await screen.findByText("Новое сообщение клиента из бота", { selector: ".pf-msg-bubble" }),
    ).toBeVisible();
  });

  it("пустая очередь — «Все передачи разобраны»", async () => {
    window.localStorage.setItem(MOCK_INBOX_EMPTY_KEY, "1");
    await open("manager@demo.example");
    expect(await screen.findByRole("heading", { name: "Все передачи разобраны" })).toBeVisible();
    expect(screen.getByText("Бот отвечает сам, пока клиент не попросит человека.")).toBeVisible();
    window.localStorage.removeItem(MOCK_INBOX_EMPTY_KEY);
  });
});

describe("Клиенты · Ждут ответа: директор", () => {
  it("видит очередь и переписку только для чтения: без «Забрать» и поля ответа", async () => {
    await open("director@demo.example", "?lead=L-2041");
    expect(await screen.findByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Забрать/ })).toBeNull();
    expect(screen.queryByLabelText("Сообщение клиенту")).toBeNull();
    expect(screen.getByText("Только просмотр: отвечают менеджеры")).toBeVisible();
  });
});

describe("лента: склейка страниц и заметок", () => {
  it("без повторов по id; заметки не старше загруженной истории, пока она не догружена", () => {
    const m = (id: number, at: string) => ({
      id,
      author: "lead" as const,
      author_name: null,
      text: String(id),
      created_at: at,
      attachments: [],
    });
    const note = {
      id: 1,
      author_name: null,
      text: "n",
      created_at: "2026-10-27T08:00:00Z",
      visible_to_bot: false,
    };
    const latest = {
      items: [m(2, "2026-10-27T09:00:00Z"), m(3, "2026-10-27T09:05:00Z")],
      notes: [note],
      has_more: true,
    };
    expect(mergeThread([], latest, false).map((e) => e.kind)).toEqual(["message", "message"]);
    const all = mergeThread(
      [m(1, "2026-10-27T07:00:00Z"), m(2, "2026-10-27T09:00:00Z")],
      latest,
      true,
    );
    expect(all.map((e) => (e.kind === "message" ? e.message.id : "note"))).toEqual([
      1,
      "note",
      2,
      3,
    ]);
  });
});

describe("итог неудачной отправки", () => {
  const t = i18n.getFixedT("ru");

  it("«Повторить» — при сбое Telegram, CRM и пока ответ ещё отправляется; без сравнения строк", () => {
    expect(
      sendFailure(
        t,
        new ApiError(502, "INTEGRATION_FAILED", "x", "crm", { reason: "delivery_failed" }),
      ),
    ).toEqual({
      text: "Не отправлено: Telegram не ответил.",
      retry: true,
    });
    expect(sendFailure(t, new ApiError(503, "BACKEND_UNAVAILABLE", "x", "crm")).retry).toBe(true);
    expect(sendFailure(t, new TypeError("Failed to fetch")).retry).toBe(true);
    const busy = sendFailure(
      t,
      new ApiError(409, "CONFLICT", "x", "crm", { reason: "reply_in_progress" }),
    );
    expect(busy).toEqual({
      text: "Сообщение ещё отправляется — подождите немного и нажмите «Повторить»",
      retry: true,
    });
    expect(
      sendFailure(t, new ApiError(409, "CONFLICT", "x", "crm", { reason: "take_first" })),
    ).toEqual({
      text: "Сначала заберите лида",
      retry: false,
    });
  });
});
