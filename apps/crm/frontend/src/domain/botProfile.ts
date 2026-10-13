/** Профиль бота в «Подключениях» (ADR-0018): итог публикации в Telegram словами. Без React. */
import type { BotProfileOut } from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatWhen } from "../lib/time";

const tt = t.botProfile;

/** Итог публикации словами: «Опубликовано в Telegram» или причина и что делать. */
export function publishText(published: BotProfileOut["published"]): {
  ok: boolean;
  text: string;
} {
  if (!published) return { ok: false, text: tt.never };
  if (published.ok) {
    return {
      ok: true,
      text: tt.publishedAt
        .replace("{when}", formatWhen(published.at))
        .replace("{changed}", String(published.changed)),
    };
  }
  const minutes = String(Math.max(1, Math.ceil((published.retry_after ?? 60) / 60)));
  const reason = published.error ?? "telegram_error";
  return { ok: false, text: (tt.errors[reason] ?? "").replace("{minutes}", minutes) };
}
