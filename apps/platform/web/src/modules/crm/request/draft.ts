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
  return ["companyName", "inn", "fullName", "phone", "email", "summary", "urgency"].every(
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
