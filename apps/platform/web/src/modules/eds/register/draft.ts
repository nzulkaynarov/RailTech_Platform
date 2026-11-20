import type { Attachment } from "../new/formModel";
import type { AiField } from "./aiFill";
import { emptyRegister, type RegisterValues } from "./registerModel";

/**
 * Черновик «Зарегистрировать входящее» (СЦ-10): поля, открытый шаг, предложение ИИ и загруженные файлы — в `sessionStorage`
 * вкладки, ключ — сотрудник. Файлы — ссылки на загрузку EDS: непривязанный файл можно приложить снова, чужой или
 * пропавший EDS отвергнет (`file_ids`), и форма уберёт его. Хранилище может быть недоступно — тогда черновика просто нет.
 */
export type RegisterSection = "file" | "sender" | "content" | "route" | "review";

export interface RegisterDraft {
  values: RegisterValues;
  active: RegisterSection;
  ai: { id: string; filled: AiField[]; left: AiField[] } | null;
  savedAt: string;
}

const PREFIX = "rt-pf-register-draft-v1";
export const REGISTER_DRAFT_TTL_MS = 24 * 60 * 60 * 1000;
export const DRAFT_FILE_KEY = "draft-";
const SECTIONS: readonly RegisterSection[] = ["file", "sender", "content", "route", "review"];

function key(userId: string): string {
  return `${PREFIX}:${userId}`;
}

function isValues(value: unknown): value is RegisterValues {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    ["kind", "receiptMethod", "senderName", "senderCompanyId", "subject"].every(
      (field) => typeof v[field] === "string",
    ) && Array.isArray(v["attachments"])
  );
}

/** Готовые файлы черновика: ключ `draft-…` не пересекается с новыми загрузками, снять такой файл можно. */
function restoredFiles(files: readonly Attachment[]): Attachment[] {
  return files.flatMap((file) =>
    file.status === "done" && file.id
      ? [
          {
            key: `${DRAFT_FILE_KEY}${file.id}`,
            name: file.name,
            size: file.size,
            status: "done" as const,
            id: file.id,
          },
        ]
      : [],
  );
}

export function readRegisterDraft(userId: string): RegisterDraft | null {
  try {
    const raw = window.sessionStorage.getItem(key(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RegisterDraft>;
    if (!isValues(parsed.values) || typeof parsed.savedAt !== "string") return null;
    if (Date.now() - Date.parse(parsed.savedAt) > REGISTER_DRAFT_TTL_MS) {
      window.sessionStorage.removeItem(key(userId));
      return null;
    }
    return {
      values: {
        ...parsed.values,
        sourceMailId: null,
        attachments: restoredFiles(parsed.values.attachments),
      },
      active: SECTIONS.includes(parsed.active as RegisterSection)
        ? (parsed.active as RegisterSection)
        : "file",
      ai: parsed.ai ?? null,
      savedAt: parsed.savedAt,
    };
  } catch {
    return null;
  }
}

/** Пустая форма (дата поступления не в счёт, нет готовых файлов) черновиком не считается: стирает прежний. */
export function isBlankRegister(values: RegisterValues, today: string): boolean {
  const comparable = (v: RegisterValues) =>
    JSON.stringify({ ...v, receivedAt: "", attachments: [] });
  return (
    comparable(values) === comparable(emptyRegister(today)) &&
    !values.attachments.some((file) => file.status === "done" && file.id)
  );
}

export function writeRegisterDraft(
  userId: string,
  today: string,
  draft: Omit<RegisterDraft, "savedAt">,
): void {
  try {
    if (isBlankRegister(draft.values, today)) {
      window.sessionStorage.removeItem(key(userId));
      return;
    }
    const values = { ...draft.values, attachments: restoredFiles(draft.values.attachments) };
    window.sessionStorage.setItem(
      key(userId),
      JSON.stringify({ ...draft, values, savedAt: new Date().toISOString() }),
    );
  } catch {
    // Не критично: без хранилища введённое живёт, пока открыта страница.
  }
}

export function clearRegisterDraft(userId: string): void {
  try {
    window.sessionStorage.removeItem(key(userId));
  } catch {
    // Не критично.
  }
}
