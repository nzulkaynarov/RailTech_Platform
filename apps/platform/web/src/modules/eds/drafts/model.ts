import type { ChecklistItem } from "../../../shared/ui/Checklist";
import type {
  QuoteApprovalCard,
  QuoteChannels,
  QuoteChecklistLine,
  QuoteSendChannel,
} from "../../../shared/api/generated/model";

export type ChecklistCode = QuoteChecklistLine["code"];

export const CHANNELS: readonly QuoteSendChannel[] = ["telegram", "cabinet", "email"];

/** Красные блокирующие строки чек-листа: пока они есть, EDS не даёт одобрить КП (визы и маржа). */
export function redBlockers(checklist: readonly QuoteChecklistLine[]): ChecklistCode[] {
  return checklist.filter((line) => line.blocking && !line.ok).map((line) => line.code);
}

/** Строка «срок клиента выдержан», если она красная: предупреждение, не блок (C1-G-1). */
export function lateWarning(checklist: readonly QuoteChecklistLine[]): QuoteChecklistLine | null {
  return checklist.find((line) => line.code === "due" && !line.ok) ?? null;
}

export interface ChannelState {
  channel: QuoteSendChannel;
  available: boolean;
  /** Почему канал недоступен: ключ подписи `form.channels.unavailable.<ключ>` */
  reason: "noTelegram" | "noCabinet" | "noEmail" | null;
}

/**
 * Каналы отправки по контакту клиента из ERP. Контакт не получен (`channels = null`) — все три выбираемы: доступность проверит
 * EDS и ERP при отправке, экран это оговаривает отдельной строкой.
 */
export function channelStates(channels: QuoteChannels | null): ChannelState[] {
  return CHANNELS.map((channel) => {
    if (channels === null) return { channel, available: true, reason: null };
    const available = channels[channel];
    const reason = !available
      ? channel === "telegram"
        ? "noTelegram"
        : channel === "cabinet"
          ? "noCabinet"
          : "noEmail"
      : null;
    return { channel, available, reason };
  });
}

/** По умолчанию отмечены все доступные каналы; бот и кабинет — основные пути КП (SPEC-v3 §3.1 шаг 5). */
export function defaultChannels(states: readonly ChannelState[]): QuoteSendChannel[] {
  return states.filter((s) => s.available).map((s) => s.channel);
}

export function isOpen(quote: Pick<QuoteApprovalCard, "status">): boolean {
  return quote.status === "open";
}

/** Строки чек-листа для показа: готово, не готово (блокирует) или предупреждение (срок). */
export function checklistItems(
  checklist: readonly QuoteChecklistLine[],
  t: (key: string, options?: Record<string, unknown>) => string,
  date: (value: string, style?: "date" | "datetime") => string,
): ChecklistItem[] {
  return checklist.map((line) => {
    const base = t(`form.checklist.${line.code}`);
    const value =
      line.value && line.code === "due" ? date(line.value) : line.value ? line.value : null;
    const state: ChecklistItem["state"] = line.ok ? "ok" : line.blocking ? "fail" : "pending";
    const label = [
      base,
      value ? ` · ${value}` : "",
      !line.ok && !line.blocking ? ` — ${t("form.checklist.warning")}` : "",
    ].join("");
    const meta = [line.by_name, line.at ? date(line.at, "datetime") : null]
      .filter(Boolean)
      .join(" · ");
    return { state, label, ...(meta ? { meta } : {}) };
  });
}
