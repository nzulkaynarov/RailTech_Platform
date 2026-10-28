import type { QuoteSendChannel } from "../../../shared/api/generated/model";

/**
 * Введённое директором: сохраняется в `sessionStorage` вкладки (переживает перезагрузку, но не закрытие вкладки и не остаётся на
 * общем компьютере), пока КП не решено, — ошибка отправки ничего не стирает. `channels: null` — выбор не менялся (берутся
 * доступные по умолчанию).
 */
export interface ApprovalDraft {
  comment: string;
  channels: QuoteSendChannel[] | null;
}

const PREFIX = "rt-pf-quote-draft-v1";

function key(userId: string, routeId: string): string {
  return `${PREFIX}:${userId}:${routeId}`;
}

function isDraft(value: unknown): value is ApprovalDraft {
  if (typeof value !== "object" || value === null) return false;
  const d = value as Record<string, unknown>;
  return (
    typeof d["comment"] === "string" &&
    (d["channels"] === null ||
      (Array.isArray(d["channels"]) && d["channels"].every((c) => typeof c === "string")))
  );
}

/** Хранилище может быть недоступно (приватное окно, заблокированные данные сайта): тогда черновика просто нет. */
export function readDraft(userId: string, routeId: string): ApprovalDraft | null {
  try {
    const raw = window.sessionStorage.getItem(key(userId, routeId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeDraft(userId: string, routeId: string, draft: ApprovalDraft): void {
  try {
    if (draft.comment.trim() === "" && draft.channels === null) {
      window.sessionStorage.removeItem(key(userId, routeId));
      return;
    }
    window.sessionStorage.setItem(key(userId, routeId), JSON.stringify(draft));
  } catch {
    // Не критично: без хранилища введённое живёт, пока открыта страница.
  }
}

export function clearDraft(userId: string, routeId: string): void {
  try {
    window.sessionStorage.removeItem(key(userId, routeId));
  } catch {
    // Не критично.
  }
}
