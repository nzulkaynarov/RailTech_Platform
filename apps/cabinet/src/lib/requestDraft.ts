/**
 * Черновик формы «Новый запрос» (C-9 аудита 2026-10-18): суть и строки переживают уход со страницы
 * (в каталог за позицией, на другой экран, случайный «назад») в `sessionStorage` вкладки.
 *
 * - Ключ — компания и контакт: на общем компьютере черновик одного контакта не всплывает у другого.
 * - Вложения хранятся ссылками `upload_id` + имя + размер (СЦ-10): файл уже лежит в ERP непривязанным; чужой или
 *   использованный сервер отвергает с `UPLOAD_NOT_FOUND` — форма убирает такие файлы и просит загрузить заново.
 * - Черновик старше суток отбрасывается: временная загрузка столько не живёт, а старый текст только мешает.
 * - Хранилище может быть недоступно (приватный режим, запрет, переполнение) — каждое обращение в try/catch,
 *   страница работает без черновика.
 */
export interface RequestDraftLine {
  text: string;
  quantity: string;
  unit: string;
}

export interface RequestDraftAttachment {
  upload_id: string;
  name: string;
  size_bytes?: number;
}

export interface RequestDraft {
  summary: string;
  lines: RequestDraftLine[];
  attachments: RequestDraftAttachment[];
  savedAt: number;
}

export const REQUEST_DRAFT_TTL_MS = 24 * 60 * 60 * 1000;

export function requestDraftKey({ companyId, contactId }: { companyId: number; contactId: number }): string {
  return `cabinet.requestDraft.v1.${companyId}.${contactId}`;
}

const isString = (value: unknown): value is string => typeof value === 'string';

function parseDraft(raw: string | null): RequestDraft | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return null;
    const { summary, lines, attachments, savedAt } = value as {
      summary?: unknown;
      lines?: unknown;
      attachments?: unknown;
      savedAt?: unknown;
    };
    if (!isString(summary) || !Array.isArray(lines)) return null;
    // Прежний формат v1 — без вложений и времени: читается как «без файлов, сохранён сейчас».
    if (attachments !== undefined && !Array.isArray(attachments)) return null;
    if (savedAt !== undefined && (typeof savedAt !== 'number' || !Number.isFinite(savedAt))) return null;
    const files: RequestDraftAttachment[] = [];
    for (const file of attachments ?? []) {
      if (typeof file !== 'object' || file === null) return null;
      const { upload_id, name, size_bytes } = file as Record<string, unknown>;
      if (!isString(upload_id) || !isString(name)) return null;
      if (size_bytes !== undefined && typeof size_bytes !== 'number') return null;
      files.push(size_bytes === undefined ? { upload_id, name } : { upload_id, name, size_bytes });
    }
    const parsed: RequestDraftLine[] = [];
    for (const line of lines) {
      if (typeof line !== 'object' || line === null) return null;
      const { text, quantity, unit } = line as Record<string, unknown>;
      if (!isString(text) || !isString(quantity) || !isString(unit)) return null;
      parsed.push({ text, quantity, unit });
    }
    return { summary, lines: parsed, attachments: files, savedAt: typeof savedAt === 'number' ? savedAt : Date.now() };
  } catch {
    return null;
  }
}

export function loadRequestDraft(key: string): RequestDraft | null {
  let draft: RequestDraft | null;
  try {
    draft = parseDraft(window.sessionStorage.getItem(key));
  } catch {
    return null;
  }
  if (draft && Date.now() - draft.savedAt > REQUEST_DRAFT_TTL_MS) {
    clearRequestDraft(key);
    return null;
  }
  return draft;
}

export function clearRequestDraft(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Хранилище недоступно — черновика и не было.
  }
}

/** Пустая форма черновиком не считается: она стирает прежний, а не пишет пустышку. */
export function saveRequestDraft(key: string, draft: Omit<RequestDraft, 'savedAt'>): void {
  const empty =
    !draft.summary.trim() &&
    draft.lines.every((line) => !line.text.trim() && !line.quantity.trim() && !line.unit.trim()) &&
    draft.attachments.length === 0;
  if (empty) {
    clearRequestDraft(key);
    return;
  }
  try {
    window.sessionStorage.setItem(key, JSON.stringify({ ...draft, savedAt: Date.now() }));
  } catch {
    // Нет места или доступа — тихо: форма продолжает работать в памяти.
  }
}
