import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/http";
import type { SmtpCheckOut, SmtpStatusOut } from "../../api/generated/model";
import { SmtpCard } from "./SmtpCard";

const notConfigured: SmtpStatusOut = {
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

const configured: SmtpStatusOut = {
  ...notConfigured,
  configured: true,
  host: "smtp.example.com",
  from_email: "crm@example.com",
  from_name: "RailTech CRM",
  settings_source: "db",
  username: "crm",
  username_source: "db",
  password_configured: true,
  password_source: "db",
  password_last4: "Q1w2",
};

const check: SmtpCheckOut = { server: "relay ESMTP", authenticated: true, latency_ms: 12 };

function renderCard(
  status: SmtpStatusOut,
  extra: Partial<React.ComponentProps<typeof SmtpCard>> = {},
): { onSave: ReturnType<typeof vi.fn>; onCheck: ReturnType<typeof vi.fn> } {
  const onSave = vi.fn();
  const onCheck = vi.fn();
  render(
    <AntApp>
      <SmtpCard
        status={status}
        saving={false}
        checking={false}
        testing={false}
        checkResult={null}
        checkError={null}
        onSave={onSave}
        onCheck={onCheck}
        onTestSend={vi.fn()}
        {...extra}
      />
    </AntApp>,
  );
  return { onSave, onCheck };
}

describe("SmtpCard", () => {
  it("shows «не настроен» and disables check and test-send without a connector", () => {
    renderCard(notConfigured);
    expect(screen.getByText("Не настроен")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить связь" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отправить тестовое письмо себе" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });

  it("never shows the relay password — only «задан ••••last4»", () => {
    renderCard(configured);
    expect(screen.getByText("Настроен")).toBeInTheDocument();
    expect(screen.getByText(/Задан: ••••Q1w2/)).toBeInTheDocument();
    expect(screen.getByText("RailTech CRM <crm@example.com>")).toBeInTheDocument();
    const password = screen.getByLabelText("Пароль SMTP");
    expect(password).toHaveValue("");
    expect(password).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Проверить связь" })).toBeEnabled();
  });

  it("asks for the admin password and keeps untouched secrets as null", async () => {
    const { onSave } = renderCard(configured);
    fireEvent.change(screen.getByLabelText("Сервер SMTP"), {
      target: { value: "smtp.sendgrid.net" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), {
      target: { value: "secret-pass" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]?.[0]).toEqual({
      host: "smtp.sendgrid.net",
      port: 587,
      security: "starttls",
      from_email: "crm@example.com",
      from_name: "RailTech CRM",
      username: null,
      smtp_password: null,
      password: "secret-pass",
    });
  });

  it("renders the check result with server banner and auth", () => {
    renderCard(configured, { checkResult: check });
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Релей отвечает");
    expect(status).toHaveTextContent("relay ESMTP");
    expect(status).toHaveTextContent("Вход выполнен");
    expect(status).toHaveTextContent("12 мс");
  });

  it("explains a failed check by details.reason without raw codes", () => {
    const error = new ApiError(502, "upstream_unavailable", "smtp check failed", {
      reason: "smtp_auth_failed",
    });
    renderCard(configured, { checkError: error });
    expect(screen.getByRole("status")).toHaveTextContent("Релей не принял логин или пароль");
    expect(screen.queryByText(/smtp_auth_failed/)).toBeNull();
  });

  it("warns without SECRETS_KEY and disables secret inputs", () => {
    renderCard({ ...notConfigured, secrets_enabled: false });
    expect(screen.getByText(/SECRETS_KEY/)).toBeInTheDocument();
    expect(screen.getByLabelText("Логин SMTP")).toBeDisabled();
    expect(screen.getByLabelText("Пароль SMTP")).toBeDisabled();
  });
});
