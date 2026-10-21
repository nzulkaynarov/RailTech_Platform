import { fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/http";
import type { ErpCheckOut, ErpStatusOut } from "../../api/generated/model";
import { ErpCard } from "./ErpCard";

const notConfigured: ErpStatusOut = {
  configured: false,
  mode: "local",
  base_url: "",
  base_url_source: "none",
  token_configured: false,
  token_source: "none",
  token_last4: null,
  token_updated_at: null,
  webhook_secret_configured: false,
  webhook_secret_source: "none",
  webhook_secret_last4: null,
  webhook_secret_updated_at: null,
  webhook_secret_previous_configured: false,
  webhook_secret_previous_source: "none",
  webhook_secret_previous_last4: null,
  webhook_secret_previous_updated_at: null,
  secrets_enabled: true,
  inbound_token_configured: false,
  inbound_token_last4: null,
  paired: false,
  previous_secret_until: null,
};

const configured: ErpStatusOut = {
  ...notConfigured,
  configured: true,
  mode: "erp",
  base_url: "http://erp.localhost",
  base_url_source: "db",
  token_configured: true,
  token_source: "db",
  token_last4: "Q1w2",
  webhook_secret_configured: true,
  webhook_secret_source: "env",
};

const health: ErpCheckOut = {
  status: "ok",
  version: "1.2.3",
  migrations_applied: true,
  queue_alive: false,
  checked_at: "2026-10-13T04:00:00Z",
  latency_ms: 42,
};

function renderCard(
  status: ErpStatusOut,
  extra: Partial<React.ComponentProps<typeof ErpCard>> = {},
): {
  onSave: ReturnType<typeof vi.fn>;
  onCheck: ReturnType<typeof vi.fn>;
  onPair: ReturnType<typeof vi.fn>;
  onRotate: ReturnType<typeof vi.fn>;
} {
  const onSave = vi.fn();
  const onCheck = vi.fn();
  const onPair = vi.fn();
  const onRotate = vi.fn();
  render(
    <AntApp>
      <ErpCard
        status={status}
        saving={false}
        checking={false}
        checkResult={null}
        checkError={null}
        onSave={onSave}
        onCheck={onCheck}
        pairing={false}
        rotating={false}
        pairError={null}
        pairCheckError={null}
        onPair={onPair}
        onRotate={onRotate}
        {...extra}
      />
    </AntApp>,
  );
  return { onSave, onCheck, onPair, onRotate };
}

/** Ручной ввод ключей — «расширенные настройки», свёрнуты, пока коннектор не настроен вручную. */
function openManual() {
  const toggle = screen.getByRole("button", { name: /Ввести ключи вручную/ });
  if (toggle.getAttribute("aria-expanded") !== "true") fireEvent.click(toggle);
}

describe("ErpCard", () => {
  it("shows «не настроен» and disables the check button without a connector", () => {
    renderCard(notConfigured);
    openManual();
    expect(screen.getByText("Не настроен")).toBeInTheDocument();
    expect(screen.getByText("автономно (без ERP)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить связь" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });

  it("never shows secret values — only «задан ••••last4» and the source", () => {
    renderCard(configured);
    expect(screen.getByText("Настроен")).toBeInTheDocument();
    expect(screen.getByText(/Задан: ••••Q1w2/)).toBeInTheDocument();
    expect(screen.getByText(/Задан в \.env \(ERP_WEBHOOK_SECRET\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить связь" })).toBeEnabled();
    const token = screen.getByLabelText("Сервисный токен CRM → ERP");
    expect(token).toHaveValue("");
    expect(token).toHaveAttribute("type", "password");
  });

  it("asks for the password and sends null for untouched secrets", async () => {
    const { onSave } = renderCard(configured);
    fireEvent.change(screen.getByLabelText("Адрес ERP", { selector: "#erp-base-url" }), {
      target: { value: "https://erp.example.com/api/integration/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), {
      target: { value: "secret-pass" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]?.[0]).toEqual({
      base_url: "https://erp.example.com/api/integration/v1",
      service_token: null,
      webhook_secret: null,
      webhook_secret_previous: null,
      clear_webhook_secret_previous: false,
      password: "secret-pass",
    });
  });

  it("rotates the webhook secret: new current, old as previous, then clears the previous", async () => {
    const { onSave } = renderCard({
      ...configured,
      webhook_secret_source: "db",
      webhook_secret_last4: "0001",
    });
    fireEvent.change(screen.getByLabelText("Секрет вебхуков ERP → CRM"), {
      target: { value: "new-webhook-secret-0002" },
    });
    fireEvent.change(screen.getAllByLabelText("Предыдущий секрет вебхуков")[0] as HTMLElement, {
      target: { value: "old-webhook-secret-0001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), { target: { value: "pw" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(onSave.mock.calls[0]?.[0]).toMatchObject({
      webhook_secret: "new-webhook-secret-0002",
      webhook_secret_previous: "old-webhook-secret-0001",
      clear_webhook_secret_previous: false,
    });
  });

  it("shows the previous secret as «Принимается ••••last4» and can clear it", async () => {
    const { onSave } = renderCard({
      ...configured,
      webhook_secret_source: "db",
      webhook_secret_last4: "0002",
      webhook_secret_previous_configured: true,
      webhook_secret_previous_source: "db",
      webhook_secret_previous_last4: "0001",
    });
    expect(screen.getByText(/Принимается: ••••0001/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Снять предыдущий секрет/ }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), { target: { value: "pw" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    expect(onSave.mock.calls[0]?.[0]).toMatchObject({
      webhook_secret: null,
      webhook_secret_previous: null,
      clear_webhook_secret_previous: true,
    });
  });

  it("offers no «снять» when the previous secret is not stored in CRM", () => {
    renderCard(configured);
    expect(screen.queryByRole("checkbox", { name: /Снять предыдущий секрет/ })).toBeNull();
  });

  it("renders the check result with version, migrations and queue", () => {
    renderCard(configured, { checkResult: health });
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("ERP отвечает");
    expect(status).toHaveTextContent("1.2.3");
    expect(status).toHaveTextContent("42 мс");
    expect(screen.getByText("Миграции применены").nextElementSibling).toHaveTextContent("Да");
    expect(screen.getByText("Очередь задач жива").nextElementSibling).toHaveTextContent("Нет");
  });

  it("explains a failed check by details.reason", () => {
    const error = new ApiError(502, "upstream_unavailable", "erp health check failed", {
      reason: "erp_unauthorized",
    });
    renderCard(configured, { checkError: error });
    expect(screen.getByRole("status")).toHaveTextContent("ERP не приняла сервисный токен");
    expect(screen.queryByText(/erp_unauthorized/)).toBeNull();
  });

  it("warns without SECRETS_KEY and disables secret inputs", () => {
    renderCard({ ...notConfigured, secrets_enabled: false });
    openManual();
    expect(screen.getByText(/SECRETS_KEY/)).toBeInTheDocument();
    expect(screen.getByLabelText("Сервисный токен CRM → ERP")).toBeDisabled();
    expect(screen.getByLabelText("Секрет вебхуков ERP → CRM")).toBeDisabled();
  });

  describe("pairing «Подключить ERP» (M3-CRM-10)", () => {
    const paired: ErpStatusOut = {
      ...configured,
      webhook_secret_source: "db",
      webhook_secret_last4: "Cd34",
      token_updated_at: "2026-10-21T05:00:00Z",
      inbound_token_configured: true,
      inbound_token_last4: "Ef56",
      paired: true,
    };

    it("offers the three steps, address and code; connect is disabled until both are filled", () => {
      renderCard(notConfigured);
      expect(screen.getByText(/Настройки → Интеграция с CRM/)).toBeInTheDocument();
      const connect = screen.getByRole("button", { name: "Подключить ERP" });
      expect(connect).toBeDisabled();
      fireEvent.change(screen.getByLabelText("Адрес ERP", { selector: "#erp-pair-base-url" }), {
        target: { value: "https://erp.example.com" },
      });
      expect(connect).toBeDisabled();
      fireEvent.change(screen.getByLabelText("Код сопряжения"), {
        target: { value: "ABCD-EFGH-JKMN" },
      });
      expect(connect).toBeEnabled();
    });

    it("asks for the password and sends address, code and password — no keys are typed", async () => {
      const { onPair } = renderCard(notConfigured);
      fireEvent.change(screen.getByLabelText("Адрес ERP", { selector: "#erp-pair-base-url" }), {
        target: { value: " https://erp.example.com " },
      });
      fireEvent.change(screen.getByLabelText("Код сопряжения"), {
        target: { value: " ABCD-EFGH-JKMN " },
      });
      fireEvent.click(screen.getByRole("button", { name: "Подключить ERP" }));
      const dialog = await screen.findByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), { target: { value: "pw" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
      expect(onPair).toHaveBeenCalledTimes(1);
      expect(onPair.mock.calls[0]?.[0]).toEqual({
        base_url: "https://erp.example.com",
        code: "ABCD-EFGH-JKMN",
        password: "pw",
      });
    });

    it("points the code error at the code field with a human explanation", () => {
      const error = new ApiError(422, "validation_failed", "pairing", {
        reason: "erp_pairing_code_expired",
        field: "code",
      });
      renderCard(notConfigured, { pairError: error });
      expect(screen.getByText(/Срок кода сопряжения вышел/)).toBeInTheDocument();
      expect(screen.queryByText(/erp_pairing_code_expired/)).toBeNull();
    });

    it("blocks pairing without SECRETS_KEY", () => {
      renderCard({ ...notConfigured, secrets_enabled: false });
      fireEvent.change(screen.getByLabelText("Адрес ERP", { selector: "#erp-pair-base-url" }), {
        target: { value: "https://erp.example.com" },
      });
      fireEvent.change(screen.getByLabelText("Код сопряжения"), { target: { value: "ABCD" } });
      expect(screen.getByRole("button", { name: "Подключить ERP" })).toBeDisabled();
    });

    it("shows the paired summary with last4 only, and no manual keys by default", () => {
      renderCard(paired);
      expect(screen.getByText("ERP сопряжена")).toBeInTheDocument();
      expect(screen.getByText("••••Q1w2")).toBeInTheDocument();
      expect(screen.getByText("••••Ef56")).toBeInTheDocument();
      expect(screen.getByText("••••Cd34")).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Код сопряжения" })).toBeNull();
      expect(screen.getByRole("button", { name: /Ввести ключи вручную/ })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    });

    it("rotates keys after the password, with the no-downtime explanation", async () => {
      const { onRotate } = renderCard(paired);
      fireEvent.click(screen.getByRole("button", { name: "Обновить ключи" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(/Работа не остановится/)).toBeInTheDocument();
      fireEvent.change(within(dialog).getByLabelText("Ваш пароль"), { target: { value: "pw" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
      expect(onRotate.mock.calls[0]?.[0]).toEqual({ password: "pw" });
    });

    it("warns when the last rotation was not confirmed by ERP and tells to repeat it", () => {
      renderCard({ ...paired, rotation_pending: true });
      expect(screen.getByText("Обновление ключей не подтверждено")).toBeInTheDocument();
      expect(screen.getByText(/повторит ту же замену/)).toBeInTheDocument();
    });

    it("explains the https requirement in production at the address field", () => {
      const error = new ApiError(422, "validation_failed", "https", {
        reason: "erp_https_required",
        field: "base_url",
      });
      renderCard(notConfigured, { pairError: error });
      expect(screen.getByText(/должен начинаться с https:\/\//)).toBeInTheDocument();
    });

    it("announces the transition after rotation", () => {
      renderCard({ ...paired, previous_secret_until: "2026-10-21T06:00:00Z" });
      expect(screen.getByRole("status")).toHaveTextContent(/Идёт переход на новые ключи/);
    });

    it("keeps pairing successful and explains a failed link check right after it", () => {
      renderCard(paired, { pairCheckError: "erp_unavailable" });
      expect(
        screen.getByText("Ключи переданы в ERP, но проверка связи не прошла"),
      ).toBeInTheDocument();
      expect(screen.getByText(/ERP не отвечает/)).toBeInTheDocument();
    });
  });
});
