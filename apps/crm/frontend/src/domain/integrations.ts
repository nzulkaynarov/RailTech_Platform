import type { TelegramStatusOut } from "../api/generated/model";

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
