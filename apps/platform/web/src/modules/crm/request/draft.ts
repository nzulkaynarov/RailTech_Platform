import { emptyRequestForm, type RequestFormState } from "./formModel";

/**
 * Черновик формы «Создать заявку» (СЦ-6): поля, открытый шаг, ключ формы и готовый файл EDS — в `sessionStorage` вкладки,
 * ключ — сотрудник и откуда открыта форма (лид, клиент или новая). Форма предлагает его кнопками «Продолжить» и «Начать
 * заново», молча ничего не подставляет. Ключ формы хранится, чтобы повтор после потерянного ответа вернул ту же заявку,
 * а файл — чтобы загруженное письмо не терялось. Хранилище может быть недоступно — тогда черновика просто нет.
 */
export type RequestSection = "client" | "contact" | "request" | "review";

export interface RequestDraft {
  state: RequestFormState;
  active: RequestSection;
  contactTouched: boolean;
  requestKey: string;
  savedAt: string;
}

const PREFIX = "rt-pf-request-draft-v1";
export const REQUEST_DRAFT_TTL_MS = 24 * 60 * 60 * 1000;
export const REQUEST_SECTIONS: readonly RequestSection[] = [
  "client",
  "contact",
  "request",
  "review",
];

/**
 * Откуда открыта форма: `letter:<id файла>` (передача из входящего), `L-0001`, `client:<id>` или `new`.
 * Форма из входящего ведёт свой черновик: он несёт файл ВХ и закрывает поручение, чужой форме его не отдать.
 */
export function requestDraftScope(
  lead: string | null,
  clientId: number | null,
  letterFileId: string | null = null,
): string {
  if (letterFileId) return `letter:${letterFileId}`;
  if (lead) return lead;
  return clientId !== null ? `client:${String(clientId)}` : "new";
}

function key(userId: string, scope: string): string {
  return `${PREFIX}:${userId}:${scope}`;
}

function isState(value: unknown): value is RequestFormState {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return ["fullName", "phone", "email", "summary", "urgency"].every(
    (field) => typeof v[field] === "string",
  );
}

/** В черновик идёт только готовый файл: загрузка и ошибка после перезагрузки страницы не продолжатся. */
function persistedLetter(state: RequestFormState): RequestFormState["letter"] {
  const letter = state.letter;
  return letter?.status === "done" && letter.id
    ? {
        name: letter.name,
        status: "done",
        id: letter.id,
        ...(letter.kind ? { kind: letter.kind } : {}),
      }
    : null;
}

export function readRequestDraft(userId: string, scope: string): RequestDraft | null {
  try {
    const raw = window.sessionStorage.getItem(key(userId, scope));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RequestDraft>;
    if (
      !isState(parsed.state) ||
      typeof parsed.savedAt !== "string" ||
      typeof parsed.requestKey !== "string"
    ) {
      return null;
    }
    if (Date.now() - Date.parse(parsed.savedAt) > REQUEST_DRAFT_TTL_MS) {
      window.sessionStorage.removeItem(key(userId, scope));
      return null;
    }
    return {
      state: { ...emptyRequestForm(), ...parsed.state, letter: persistedLetter(parsed.state) },
      active: REQUEST_SECTIONS.includes(parsed.active as RequestSection)
        ? (parsed.active as RequestSection)
        : "client",
      contactTouched: parsed.contactTouched === true,
      requestKey: parsed.requestKey,
      savedAt: parsed.savedAt,
    };
  } catch {
    return null;
  }
}

/** Форма, в которой человек ничего не менял (и нет готового файла), черновиком не считается: стирает прежний. */
export function isBlankRequest(
  state: RequestFormState,
  initial: RequestFormState,
  ignoreLetter: boolean,
): boolean {
  const comparable = (v: RequestFormState) => JSON.stringify({ ...v, letter: null });
  // Записка о звонке система собирает сама при открытии формы: сама по себе черновиком она не считается.
  const systemLetter = state.letter?.kind === "call_note";
  return (
    comparable(state) === comparable(initial) &&
    (ignoreLetter || systemLetter || persistedLetter(state) === null)
  );
}

export function writeRequestDraft(
  userId: string,
  scope: string,
  initial: RequestFormState,
  /** Файл пришёл вместе с формой (письмо из переписки или входящего) — сам по себе черновиком не считается */
  ignoreLetter: boolean,
  draft: Omit<RequestDraft, "savedAt">,
): void {
  try {
    if (isBlankRequest(draft.state, initial, ignoreLetter)) {
      window.sessionStorage.removeItem(key(userId, scope));
      return;
    }
    window.sessionStorage.setItem(
      key(userId, scope),
      JSON.stringify({
        ...draft,
        state: { ...draft.state, letter: persistedLetter(draft.state) },
        savedAt: new Date().toISOString(),
      }),
    );
  } catch {
    // Не критично: без хранилища введённое живёт, пока открыта форма.
  }
}

export function clearRequestDraft(userId: string, scope: string): void {
  try {
    window.sessionStorage.removeItem(key(userId, scope));
  } catch {
    // Не критично.
  }
}

export interface ListedDraft {
  scope: string;
  draft: RequestDraft;
}

/**
 * Все черновики сотрудника в этой вкладке — для вкладки «Черновики» реестра заявок (ЗАЯВ-1). Черновик из входящего
 * (`letter:…`) не показывается: его продолжает сама передача из входящего. Новее — выше.
 */
export function listRequestDrafts(userId: string): ListedDraft[] {
  const rows: ListedDraft[] = [];
  try {
    const prefix = `${PREFIX}:${userId}:`;
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const name = window.sessionStorage.key(i);
      if (!name?.startsWith(prefix)) continue;
      const scope = name.slice(prefix.length);
      if (scope.startsWith("letter:")) continue;
      const draft = readRequestDraft(userId, scope);
      if (draft) rows.push({ scope, draft });
    }
  } catch {
    return [];
  }
  return rows.sort((a, b) => b.draft.savedAt.localeCompare(a.draft.savedAt));
}

/** Куда ведёт «Продолжить»: форма того же места, откуда черновик начат (клиент, лид или новая). */
export function draftContinuePath(scope: string, mobile: boolean): string {
  // На телефоне форма — лист, боковое окно не нужно; на широком экране форма живёт в боковом окне
  const open = mobile ? "create=1" : "create=1&panel=open&tab=card";
  if (scope.startsWith("client:")) {
    return `/crm/clients?client=${encodeURIComponent(scope.slice("client:".length))}&${open}`;
  }
  if (scope === "new") return `/crm/clients?${open}`;
  return `/crm/leads?lead=${encodeURIComponent(scope)}&${open}`;
}

/** Вернуть удалённый черновик («Вернуть» в уведомлении): запись целиком, как была. */
export function restoreRequestDraft(userId: string, scope: string, draft: RequestDraft): void {
  try {
    window.sessionStorage.setItem(key(userId, scope), JSON.stringify(draft));
  } catch {
    // Не критично.
  }
}
