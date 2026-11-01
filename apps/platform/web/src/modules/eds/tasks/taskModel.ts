import type { Attachment } from "../new/formModel";

/** Тело «Исполнено» (pure): отчёт, загруженные файлы, номер ИСХ; хотя бы что-то одно — иначе `null`. */
export function completeBody(
  report: string,
  attachments: readonly Attachment[],
  outgoing: string,
): { report: string | null; file_ids: string[]; outgoing_number: string | null } | null {
  const ids = attachments.flatMap((a) => (a.status === "done" && a.id ? [a.id] : []));
  const text = report.trim();
  const number = outgoing.trim();
  if (!text && ids.length === 0 && !number) return null;
  return { report: text || null, file_ids: [...new Set(ids)], outgoing_number: number || null };
}
