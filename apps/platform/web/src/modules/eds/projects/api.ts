/** Путь карточки проекта в SPA: номер `ПР-2026-104` в адресе кодируется (в номерах других документов бывает «/»). */
export function projectPath(number: string): string {
  return `/eds/projects/${encodeURIComponent(number)}`;
}

/** Номер или id сделки в адресе API. */
export function projectRef(objectId: string): string {
  return encodeURIComponent(objectId);
}

export type Scope = "all" | "mine";

export function scopeOf(value: string | null): Scope {
  return value === "mine" ? "mine" : "all";
}

export const PAGE_SIZE = 25;

export function fileUrl(
  objectId: string,
  kind: "contract" | "invoice" | "act",
  docId: number,
  variant: "pdf" | "scan",
): string {
  return `/api/v1/eds/projects/${projectRef(objectId)}/files/${kind}/${String(docId)}?variant=${variant}`;
}
