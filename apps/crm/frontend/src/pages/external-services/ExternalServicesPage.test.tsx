/**
 * «Внешние сервисы» (M3-CRM-12): хуки запросов подменены — без сервера. Каркас (один h1, группы),
 * «что сделать» с кнопкой к настройке, баннер «выключено вручную», выключатель с паролем,
 * деталка с инцидентами; на экране нет сырых ключей.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ExternalServiceDetailOut,
  ExternalServiceOut,
  ExternalServicesOut,
} from "../../api/generated/model";
import { ExternalServiceDetailPage } from "./ExternalServiceDetailPage";
import { ExternalServicesPage } from "./ExternalServicesPage";

const base: ExternalServiceOut = {
  key: "docling",
  title: "Распознавание документов (docling)",
  purpose: "Текст из PDF",
  system: "crm",
  source: "crm",
  check: "health",
  frequency: "minute",
  status: "ok",
  summary: "Сервис отвечает",
  error: null,
  hint: null,
  fix_path: "/kb",
  checked_at: "2026-10-14T08:59:00Z",
  stale: false,
  latency_ms: 20,
  metrics: {},
  uptime_24h: 1,
  uptime_7d: 1,
  checks_24h: 1440,
  failures_24h: 0,
  p95_ms_24h: 30,
  switch: null,
  incident: null,
};

const telegram: ExternalServiceOut = {
  ...base,
  key: "telegram",
  title: "Telegram Bot API",
  status: "fail",
  summary: "Telegram не принимает токен бота — бот не работает",
  error: "getMe: HTTP 401",
  hint: "Выпустите новый токен у @BotFather и введите в «Подключениях» → «Telegram-бот»",
  fix_path: "/integrations?tab=bot",
  uptime_24h: 0.5,
  switch: {
    kind: "telegram",
    available: true,
    disabled: false,
    effect: "Бот перестанет отвечать клиентам",
    problem: null,
    reason: null,
    changed_at: null,
    changed_by: null,
  },
  incident: {
    id: 1,
    started_at: "2026-10-14T08:50:00Z",
    ended_at: null,
    duration_s: null,
    summary: "Telegram не принимает токен",
    last_error: "getMe: HTTP 401",
    alerted: true,
    recovery_alerted: false,
  },
};

const mail: ExternalServiceOut = {
  ...base,
  key: "mail",
  title: "Почтовый релей (SMTP)",
  status: "ok",
  summary: "Письма уходят",
  metrics: { sent_24h: 4, _smtp: "ok" },
  switch: {
    kind: "mail",
    available: true,
    disabled: true,
    effect: "Письма будут копиться",
    problem: null,
    reason: "переезд релея",
    changed_at: "2026-10-14T08:00:00Z",
    changed_by: "Нурбек",
  },
};

const gemini: ExternalServiceOut = {
  ...base,
  key: "vendor.gemini",
  title: "Модели ИИ: Google Gemini",
  switch: {
    kind: "vendor",
    available: false,
    disabled: false,
    effect: "",
    problem: "Этот провайдер обслуживает запасную модель",
    reason: null,
    changed_at: null,
    changed_by: null,
  },
};

const erp: ExternalServiceOut = {
  ...base,
  key: "erp.cbu_rates",
  title: "Курсы ЦБ",
  system: "erp",
  source: "erp",
  frequency: "erp",
  status: "unknown",
  summary: "Нет данных: ERP пока не передаёт состояние",
  checked_at: null,
};

const list: ExternalServicesOut = {
  checked_at: "2026-10-14T08:59:00Z",
  summary: { ok: 3, warn: 0, fail: 1, unknown: 1, off: 0, disabled: 1 },
  services: [base, telegram, mail, gemini, erp],
};

const detail: ExternalServiceDetailOut = {
  service: telegram,
  checks: [
    {
      checked_at: "2026-10-14T08:59:00Z",
      tier: "cheap",
      status: "fail",
      latency_ms: 40,
      summary: "Telegram не принимает токен бота",
      error: "getMe: HTTP 401",
    },
  ],
  days: [{ day: "2026-10-14", ok: 10, warn: 0, fail: 10, unknown: 0, uptime: 0.5 }],
  incidents: telegram.incident ? [telegram.incident] : [],
};

const disable = { mutate: vi.fn(), isPending: false };
const enable = { mutate: vi.fn(), isPending: false };
const check = { mutate: vi.fn(), isPending: false };
const query = <T,>(data: T) => ({
  data,
  isLoading: false,
  isError: false,
  error: null,
  isFetching: false,
  refetch: vi.fn(() => Promise.resolve()),
});

vi.mock("../../api/externalServiceQueries", () => ({
  useExternalServices: () => query(list),
  useExternalService: () => query(detail),
  useCheckService: () => check,
  useServiceSwitch: () => ({ disable, enable }),
}));

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/external-services" element={<ExternalServicesPage />} />
            <Route path="/external-services/:key" element={<ExternalServiceDetailPage />} />
            <Route path="/integrations" element={<p>Подключения открыты</p>} />
          </Routes>
        </MemoryRouter>
      </AntApp>
    </QueryClientProvider>,
  );
}

describe("ExternalServicesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("has one h1, a status summary and groups with problems first", () => {
    renderAt("/external-services");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Внешние сервисы" })).toBeVisible();
    const summary = screen.getByRole("status", { name: "Сводка по внешним сервисам" });
    expect(within(summary).getByText("Сбой: 1")).toBeInTheDocument();
    expect(within(summary).getByText("Выключено вручную: 1")).toBeInTheDocument();
    const groups = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(groups).toEqual(["Требуют внимания", "Выключены вручную", "Работают", "Сервисы ERP"]);
    expect(document.body.textContent).not.toMatch(/_smtp|erp\.cbu_rates|vendor\./);
  });

  it("shows what to do and leads to the connector", () => {
    renderAt("/external-services");
    expect(screen.getByText(/Что сделать: Выпустите новый токен/)).toBeInTheDocument();
    expect(screen.getByText("Ошибка: getMe: HTTP 401")).toBeInTheDocument();
    const [fix] = screen.getAllByRole("button", { name: "Исправить" });
    if (!fix) throw new Error("no fix button");
    fireEvent.click(fix);
    expect(screen.getByText("Подключения открыты")).toBeInTheDocument();
  });

  it("banners a manually disabled service and explains why a switch is unavailable", () => {
    renderAt("/external-services");
    expect(screen.getByText("Выключено вручную: Почтовый релей (SMTP)")).toBeInTheDocument();
    expect(screen.getByText(/переезд релея · Нурбек/)).toBeInTheDocument();
    expect(
      screen.getByText("Выключить нельзя: Этот провайдер обслуживает запасную модель"),
    ).toBeInTheDocument();
  });

  it("asks for the admin password before switching off", () => {
    renderAt("/external-services");
    fireEvent.click(screen.getByRole("button", { name: "Выключить" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Бот перестанет отвечать клиентам")).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Выключить" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), { target: { value: "pw" } });
    fireEvent.change(within(dialog).getByLabelText(/Причина/), { target: { value: "спам" } });
    fireEvent.click(confirm);
    expect(disable.mutate).toHaveBeenCalledWith({
      key: "telegram",
      data: { password: "pw", reason: "спам" },
    });
  });

  it("checks a service now, but not ERP-reported ones", () => {
    renderAt("/external-services");
    const buttons = screen.getAllByRole("button", { name: "Проверить сейчас" });
    expect(buttons).toHaveLength(4);
    const [first] = buttons;
    if (!first) throw new Error("no check button");
    fireEvent.click(first);
    expect(check.mutate).toHaveBeenCalledWith({ key: "telegram" }, expect.anything());
  });
});

describe("ExternalServiceDetailPage", () => {
  it("shows state, metrics, 7 days, checks and incidents", () => {
    renderAt("/external-services/telegram");
    expect(screen.getByRole("heading", { level: 1, name: "Telegram Bot API" })).toBeVisible();
    expect(screen.getByText(/Сбой с /)).toBeInTheDocument();
    expect(screen.getByText("Инциденты за 30 дней")).toBeInTheDocument();
    expect(screen.getByText("идёт сейчас")).toBeInTheDocument();
    expect(screen.getByText("Проверки за 24 часа")).toBeInTheDocument();
    expect(screen.getByLabelText(/Доступность: 50/)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
