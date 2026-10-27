import type { LetterZone } from "../../../shared/api/generated/model";

export interface ZonePick {
  on: boolean;
  /** `crm_user_id` выбранного сотрудника; пусто — не выбран */
  userId: string;
}

/** Введённое директором: сохраняется в браузере, пока письмо не решено, — ошибка отправки ничего не стирает. */
export interface ResolutionDraft {
  text: string;
  picks: Record<LetterZone, ZonePick>;
  due: string;
  margin: string;
  comment: string;
}

const PREFIX = "rt-pf-letter-draft-v1";

function key(userId: string, letterId: string): string {
  return `${PREFIX}:${userId}:${letterId}`;
}

function isDraft(value: unknown): value is ResolutionDraft {
  if (typeof value !== "object" || value === null) return false;
  const d = value as Record<string, unknown>;
  return (
    typeof d["text"] === "string" &&
    typeof d["due"] === "string" &&
    typeof d["margin"] === "string" &&
    typeof d["comment"] === "string" &&
    typeof d["picks"] === "object" &&
    d["picks"] !== null
  );
}

/** Хранилище может быть недоступно (приватное окно, заблокированные данные сайта): тогда черновика просто нет. */
export function readDraft(userId: string, letterId: string): ResolutionDraft | null {
  try {
    const raw = window.localStorage.getItem(key(userId, letterId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeDraft(userId: string, letterId: string, draft: ResolutionDraft): void {
  try {
    if (draft.text.trim() === "" && draft.comment.trim() === "") {
      window.localStorage.removeItem(key(userId, letterId));
      return;
    }
    window.localStorage.setItem(key(userId, letterId), JSON.stringify(draft));
  } catch {
    // Не критично: без хранилища введённое живёт, пока открыта страница.
  }
}

export function clearDraft(userId: string, letterId: string): void {
  try {
    window.localStorage.removeItem(key(userId, letterId));
  } catch {
    // Не критично.
  }
}
