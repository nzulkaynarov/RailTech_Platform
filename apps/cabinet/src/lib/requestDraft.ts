/**
 * Черновик формы «Новый запрос» (C-9 аудита 2026-10-18): суть и строки переживают уход со страницы
 * (в каталог за позицией, на другой экран, случайный «назад») в `sessionStorage` вкладки.
 *
 * - Ключ — компания и контакт: на общем компьютере черновик одного контакта не всплывает у другого.
 * - Вложения не сохраняются: загруженный файл живёт в ERP как временный `upload_id`, ссылку на него через
 *   перезагрузку тащить нельзя; их клиент прикрепит заново.
 * - Хранилище может быть недоступно (приватный режим, запрет, переполнение) — каждое обращение в try/catch,
 *   страница работает без черновика.
 */
export interface RequestDraftLine {
  text: string;
  quantity: string;
  unit: string;
}

export interface RequestDraft {
  summary: string;
  lines: RequestDraftLine[];
}

export function requestDraftKey({ companyId, contactId }: { companyId: number; contactId: number }): string {
  return `cabinet.requestDraft.v1.${companyId}.${contactId}`;
}

const isString = (value: unknown): value is string => typeof value === 'string';

function parseDraft(raw: string | null): RequestDraft | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return null;
    const { summary, lines } = value as { summary?: unknown; lines?: unknown };
    if (!isString(summary) || !Array.isArray(lines)) return null;
    const parsed: RequestDraftLine[] = [];
    for (const line of lines) {
      if (typeof line !== 'object' || line === null) return null;
      const { text, quantity, unit } = line as Record<string, unknown>;
      if (!isString(text) || !isString(quantity) || !isString(unit)) return null;
      parsed.push({ text, quantity, unit });
    }
    return { summary, lines: parsed };
  } catch {
    return null;
  }
}

export function loadRequestDraft(key: string): RequestDraft | null {
  try {
    return parseDraft(window.sessionStorage.getItem(key));
  } catch {
    return null;
  }
}

export function clearRequestDraft(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Хранилище недоступно — черновика и не было.
  }
}

/** Пустая форма черновиком не считается: она стирает прежний, а не пишет пустышку. */
export function saveRequestDraft(key: string, draft: RequestDraft): void {
  const empty = !draft.summary.trim() && draft.lines.every((line) => !line.text.trim() && !line.quantity.trim() && !line.unit.trim());
  if (empty) {
    clearRequestDraft(key);
    return;
  }
  try {
    window.sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Нет места или доступа — тихо: форма продолжает работать в памяти.
  }
}
