/** Журнал писем (M3-CRM-08): хук подменён — статусы словами, фильтр, пустое состояние. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EmailLogItem, ListEmailLogParams } from "../../api/generated/model";
import { MailLog } from "./MailLog";

const rows: EmailLogItem[] = [
  {
    id: 2,
    to_email: "aziz@railtech.uz",
    subject: "Приглашение в CRM RailTech",
    template: "invite",
    lang: "ru",
    status: "sent",
    error: null,
    attempts: 1,
    user_id: 7,
    requested_by: 1,
    created_at: "2026-10-13T04:00:00Z",
    sent_at: "2026-10-13T04:00:05Z",
    source: "crm",
    purpose: "invite",
    attachments: 0,
  },
  {
    id: 1,
    to_email: "admin@railtech.uz",
    subject: "Проверка коннектора «Почта» CRM",
    template: "test",
    lang: "ru",
    status: "skipped_no_smtp",
    error: "smtp_not_configured",
    attempts: 0,
    user_id: 1,
    requested_by: 1,
    created_at: "2026-10-13T03:00:00Z",
    sent_at: null,
    source: "crm",
    purpose: "test",
    attachments: 0,
  },
];

const calls: ListEmailLogParams[] = [];
let data: EmailLogItem[] = rows;

vi.mock("../../api/integrationQueries", () => ({
  useEmailLog: (params: ListEmailLogParams) => {
    calls.push(params);
    return {
      data,
      isLoading: false,
      isError: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(() => Promise.resolve()),
    };
  },
}));

function renderLog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <MailLog />
      </AntApp>
    </QueryClientProvider>,
  );
}

describe("MailLog", () => {
  beforeEach(() => {
    calls.length = 0;
    data = rows;
    // Десктоп: таблица (на телефоне — карточки).
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("min-width"),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists letters with statuses in words, not codes", () => {
    renderLog();
    expect(screen.getByRole("heading", { level: 2, name: "Журнал писем" })).toBeInTheDocument();
    expect(screen.getByText("aziz@railtech.uz")).toBeInTheDocument();
    expect(screen.getByText("Отправлено")).toBeInTheDocument();
    expect(screen.getByText("Пропущено: почта не настроена")).toBeInTheDocument();
    expect(screen.getByText("Приглашение")).toBeInTheDocument();
    expect(screen.getByText("Тестовое")).toBeInTheDocument();
    expect(screen.queryByText("skipped_no_smtp")).toBeNull();
  });

  it("passes the status filter to the query", () => {
    renderLog();
    expect(calls[0]).toEqual({ limit: 50 });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Статус письма" }));
    fireEvent.click(screen.getByText("Ошибка", { selector: ".ant-select-item-option-content" }));
    expect(calls.at(-1)).toEqual({ status: "failed", limit: 50 });
  });

  it("shows an empty state when there are no letters", () => {
    data = [];
    renderLog();
    expect(screen.getByText("Писем пока нет")).toBeInTheDocument();
  });
});
