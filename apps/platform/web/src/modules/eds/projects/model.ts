import type { TFunction } from "i18next";

import type {
  ProjectAct,
  ProjectContract,
  ProjectJournalEntry,
} from "../../../shared/api/generated/model";

/** Фраза журнала: перевод по коду события ERP, иначе запасной русский текст ERP. */
export function journalText(t: TFunction<"projects">, entry: ProjectJournalEntry): string {
  const key = `journal.${entry.code}`;
  return entry.code && t(key, { defaultValue: "" }) !== "" ? t(key) : entry.text;
}

/** Состояние договора для подписи под статусом: «Проект» делится на не отправленный и уже у клиента. */
export function contractStateKey(
  contract: Pick<ProjectContract, "status" | "sent_to_client">,
): string {
  if (contract.status === "project") return contract.sent_to_client ? "atClient" : "project";
  return contract.status;
}

export function actStateKey(act: Pick<ProjectAct, "status">): string {
  return act.status;
}

/** Последняя запись истории документа (в ответе новые первыми). */
export function lastEntry(
  history: readonly ProjectJournalEntry[],
): ProjectJournalEntry | undefined {
  return history[0];
}

/** Файл скана подходит: PDF или изображение (JPG, PNG, WEBP) до 20 МБ — те же правила, что проверит ERP. */
export const MAX_SCAN_BYTES = 20 * 1024 * 1024;
const SCAN_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/webp"]);
const SCAN_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".webp"];

export type ScanProblem = "tooLarge" | "wrongType" | "empty";

export function scanProblem(file: Pick<File, "name" | "size" | "type">): ScanProblem | null {
  if (file.size === 0) return "empty";
  if (file.size > MAX_SCAN_BYTES) return "tooLarge";
  const name = file.name.toLowerCase();
  const okName = SCAN_EXTENSIONS.some((ext) => name.endsWith(ext));
  const okType = file.type === "" || SCAN_TYPES.has(file.type);
  return okName && okType ? null : "wrongType";
}
