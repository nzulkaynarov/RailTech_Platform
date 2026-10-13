/**
 * Страница «Подключения» с вкладкой «ERP» (M3-CRM-02): orval-хуки подменены — без сервера.
 * Проверяет каркас (h1, вкладки, состояние во вкладке) и что секреты не попадают на экран.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ErpStatusOut, SmtpStatusOut, TelegramStatusOut } from "../../api/generated/model";
import { IntegrationsPage } from "./IntegrationsPage";

const smtp: SmtpStatusOut = {
  configured: false,
  host: "",
  port: 587,
  security: "starttls",
  from_email: "",
  from_name: "",
  settings_source: "none",
  username: "",
  username_source: "none",
  password_configured: false,
  password_source: "none",
  password_last4: null,
  password_updated_at: null,
  secrets_enabled: true,
};

const telegram: TelegramStatusOut = {
  configured: true,
  source: "db",
  last4: "AbCd",
  updated_at: null,
  username: "rt_bot",
  mode: "polling",
  running: true,
  last_error: null,
  secrets_enabled: true,
  channel_id: -100,
  channel_title: "Команда",
};

const erp: ErpStatusOut = {
  configured: false,
  mode: "local",
  base_url: "http://erp.localhost",
  base_url_source: "db",
  token_configured: false,
  token_source: "none",
  token_last4: null,
  token_updated_at: null,
  webhook_secret_configured: false,
  webhook_secret_source: "none",
  webhook_secret_last4: null,
  webhook_secret_updated_at: null,
  secrets_enabled: true,
};

const query = <T,>(data: T) => ({
  data,
  isLoading: false,
  isError: false,
  error: null,
  isFetching: false,
  refetch: vi.fn(() => Promise.resolve()),
});
const mutation = () => ({
  mutate: vi.fn(),
  reset: vi.fn(),
  isPending: false,
  data: undefined,
  error: null,
});

vi.mock("../../api/integrationQueries", () => ({
  useTelegramStatus: () => query(telegram),
  useErpStatus: () => query(erp),
  useTelegramChannels: () => query([]),
  useTelegramMutations: () => ({
    saveToken: mutation(),
    connect: mutation(),
    sendTest: mutation(),
  }),
  useErpMutations: () => ({ save: mutation(), check: mutation() }),
  useSmtpStatus: () => query(smtp),
  useSmtpMutations: () => ({ save: mutation(), check: mutation(), testSend: mutation() }),
  useEmailLog: () => query([]),
  emailLogKey: () => ["/api/v1/integrations/smtp/log"],
}));
vi.mock("../../api/templateQueries", () => ({ useBotProfile: () => query(undefined) }));

function renderPage(search: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <MemoryRouter initialEntries={[`/integrations${search}`]}>
          <IntegrationsPage />
        </MemoryRouter>
      </AntApp>
    </QueryClientProvider>,
  );
}

describe("IntegrationsPage — ERP tab", () => {
  // Десктоп: вкладки (на телефоне те же разделы — раскрывающимся списком, `UrlTabs`).
  beforeEach(() => {
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

  it("has one h1 and an «ERP» tab with its state for screen readers", () => {
    renderPage("?tab=erp");
    expect(screen.getByRole("heading", { level: 1, name: "Подключения" })).toBeInTheDocument();
    const tab = screen.getByRole("tab", { name: /ERP/ });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(within(tab).getByText(/требует внимания/)).toBeInTheDocument();
  });

  it("renders the ERP card: address, write-only secrets, check button", () => {
    renderPage("?tab=erp");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("Настроен не полностью")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Адрес ERP")).toHaveValue("http://erp.localhost");
    expect(within(panel).getByLabelText("Сервисный токен CRM → ERP")).toHaveValue("");
    expect(within(panel).getByRole("button", { name: "Проверить связь" })).toBeDisabled();
    expect(document.body.textContent).not.toMatch(/[a-z]+_[a-z]+_[a-z]+/);
  });

  it("renders the «Почта» tab (M3-CRM-08): connector form and the mail journal", () => {
    renderPage("?tab=smtp");
    const tab = screen.getByRole("tab", { name: /Почта/ });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(within(tab).getByText(/не настроено/)).toBeInTheDocument();
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByLabelText("Сервер SMTP")).toHaveValue("");
    expect(within(panel).getByLabelText("Пароль SMTP")).toHaveValue("");
    expect(within(panel).getByRole("button", { name: "Проверить связь" })).toBeDisabled();
    expect(within(panel).getByRole("heading", { level: 2, name: "Журнал писем" })).toBeVisible();
    expect(within(panel).getByText("Писем пока нет")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
