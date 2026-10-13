import type {
  BotProfileOut,
  ErpStatusOut,
  SmtpStatusOut,
  TelegramStatusOut,
} from "../api/generated/model";

export type BotState = "running" | "stopped" | "notConfigured" | "failed";

/** Состояние бота для бейджа: токена нет → «не задан»; ошибка старта → «ошибка». */
export function botState(
  status: Pick<TelegramStatusOut, "configured" | "running" | "last_error">,
): BotState {
  if (status.running) return "running";
  if (!status.configured) return "notConfigured";
  return status.last_error ? "failed" : "stopped";
}

export const BOT_STATE_COLOR: Record<BotState, string> = {
  running: "success",
  stopped: "default",
  notConfigured: "warning",
  failed: "error",
};

/** Подпись канала: название из найденных, иначе id. */
export function channelLabel(
  id: number | null,
  title: string | null,
  unknown: string,
): string | null {
  if (id === null) return null;
  return title ?? unknown.replace("{id}", String(id));
}

/** Значок состояния во вкладке «Подключений» (antd `Badge status`). */
export type TabStatus = "success" | "error" | "warning" | "default";

const BOT_TAB: Record<BotState, TabStatus> = {
  running: "success",
  stopped: "default",
  notConfigured: "warning",
  failed: "error",
};

/** Состояние каждой вкладки из уже загруженных данных; профиль ещё не загружен — без значка. */
export function integrationTabStatus(
  status: TelegramStatusOut,
  profile: BotProfileOut | undefined,
): Record<"bot" | "profile" | "channel", TabStatus | null> {
  const published = profile?.published;
  let profileStatus: TabStatus | null = null;
  if (profile) profileStatus = published ? (published.ok ? "success" : "warning") : "default";
  return {
    bot: BOT_TAB[botState(status)],
    profile: profileStatus,
    channel: status.channel_id === null ? "warning" : "success",
  };
}

export type ErpState = "configured" | "partial" | "notConfigured";

/** Коннектор ERP: адрес и токен есть → настроен; только одно из двух → не полностью. */
export function erpState(
  status: Pick<ErpStatusOut, "configured" | "base_url" | "token_configured">,
): ErpState {
  if (status.configured) return "configured";
  return status.base_url || status.token_configured ? "partial" : "notConfigured";
}

export const ERP_STATE_COLOR: Record<ErpState, string> = {
  configured: "success",
  partial: "warning",
  notConfigured: "default",
};

/** Значок вкладки «ERP»: не настроен — без тревоги (CRM автономна), наполовину — внимание. */
export function erpTabStatus(status: ErpStatusOut | undefined): TabStatus | null {
  if (!status) return null;
  return ERP_STATE_COLOR[erpState(status)] as TabStatus;
}

export type SmtpState = "configured" | "partial" | "notConfigured";

/** Коннектор «Почта» (M3-CRM-08): хост и отправитель есть → настроен; одно из двух → не полностью. */
export function smtpState(
  status: Pick<SmtpStatusOut, "configured" | "host" | "from_email">,
): SmtpState {
  if (status.configured) return "configured";
  return status.host || status.from_email ? "partial" : "notConfigured";
}

export const SMTP_STATE_COLOR: Record<SmtpState, string> = ERP_STATE_COLOR;

/** Значок вкладки «Почта»: без коннектора — без тревоги (пароль выдаётся вручную, Q-010). */
export function smtpTabStatus(status: SmtpStatusOut | undefined): TabStatus | null {
  if (!status) return null;
  return SMTP_STATE_COLOR[smtpState(status)] as TabStatus;
}

/** Цвет строки журнала писем по статусу (`email_log.status`). */
export const EMAIL_STATUS_COLOR: Record<string, string> = {
  queued: "processing",
  sent: "success",
  failed: "error",
  skipped_no_smtp: "warning",
};

/** Типовой порт по способу шифрования — подсказка при смене селектора, не правило. */
export const SMTP_DEFAULT_PORT: Record<SmtpStatusOut["security"], number> = {
  starttls: 587,
  ssl: 465,
  none: 25,
};
