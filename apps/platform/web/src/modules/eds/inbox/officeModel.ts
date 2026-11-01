import type {
  LetterCard,
  LetterResolutionKind,
  OfficeResolutionIn,
  ResolutionDraftIn,
} from "../../../shared/api/generated/model";

/**
 * Резолюция пути делопроизводства (P8b, SPEC-v3 §3.2a п. 2): три типа, ответственный — любой активный сотрудник, срок с
 * подсказкой EDS (`suggested_due`), текст — шаблон по типу, соисполнители и «ознакомить». Здесь только состояние формы и
 * тело запроса; что допустимо (срок, сотрудники, путь), решает EDS.
 */
export const RESOLUTION_KINDS: readonly LetterResolutionKind[] = ["execute", "reply", "info"];

export interface OfficeValues {
  kind: LetterResolutionKind | "";
  responsibleId: string;
  due: string;
  text: string;
  /** Текст — шаблон типа, его не правили: смена типа меняет и текст */
  templated: boolean;
  coIds: string[];
  acquaintIds: string[];
}

export type OfficeField = "kind" | "responsible" | "due" | "text";
export type OfficeErrors = Partial<Record<OfficeField, "required" | "past">>;

/** «Для сведения» — без ответственного и срока (поручения нет). */
export function needsExecutor(kind: OfficeValues["kind"]): boolean {
  return kind === "execute" || kind === "reply";
}

/** Начальные значения: проект делопроизводителя, если есть, иначе подсказка срока EDS и шаблон «К исполнению». */
export function initialOffice(
  letter: Pick<LetterCard, "resolution_draft" | "suggested_due">,
  template: (kind: LetterResolutionKind) => string,
): OfficeValues {
  const draft = letter.resolution_draft;
  const kind: LetterResolutionKind = draft?.kind ?? "execute";
  const draftText = draft?.text?.trim() ?? "";
  return {
    kind,
    responsibleId: draft?.responsible?.id ?? "",
    due: needsExecutor(kind) ? (draft?.due ?? letter.suggested_due ?? "") : "",
    text: draftText || template(kind),
    templated: draftText === "",
    coIds: draft?.co_executors.map((p) => p.id) ?? [],
    acquaintIds: draft?.acquaint.map((p) => p.id) ?? [],
  };
}

/** Смена типа: шаблон текста меняется, если текст не правили; у «Для сведения» нет ответственного, срока и соисполнителей. */
export function switchKind(
  values: OfficeValues,
  kind: LetterResolutionKind,
  template: (kind: LetterResolutionKind) => string,
  suggestedDue: string | null | undefined,
): OfficeValues {
  const executor = needsExecutor(kind);
  return {
    ...values,
    kind,
    text: values.templated ? template(kind) : values.text,
    responsibleId: executor ? values.responsibleId : "",
    due: executor ? values.due || suggestedDue || "" : "",
    coIds: executor ? values.coIds : [],
  };
}

/** Проверка перед отправкой резолюции: тип, текст; у «К исполнению» и «Подготовить ответ» — ответственный и срок не в прошлом. */
export function validateOffice(values: OfficeValues, today: string): OfficeErrors {
  const errors: OfficeErrors = {};
  if (!values.kind) errors.kind = "required";
  if (values.text.trim() === "") errors.text = "required";
  if (needsExecutor(values.kind)) {
    if (!values.responsibleId) errors.responsible = "required";
    if (!values.due) errors.due = "required";
    else if (values.due < today) errors.due = "past";
  }
  return errors;
}

/** Проект проверяется мягче: всё необязательно, только срок не в прошлом. */
export function validateDraft(values: OfficeValues, today: string): OfficeErrors {
  return values.due && values.due < today ? { due: "past" } : {};
}

const uniq = (ids: readonly string[], skip: string) =>
  [...new Set(ids)].filter((id) => id !== "" && id !== skip);

export function toOfficeBody(values: OfficeValues): OfficeResolutionIn {
  const executor = needsExecutor(values.kind);
  return {
    kind: values.kind as LetterResolutionKind,
    text: values.text.trim(),
    responsible_id: executor ? values.responsibleId : null,
    due: executor ? values.due : null,
    co_executor_ids: executor ? uniq(values.coIds, values.responsibleId) : [],
    acquaint_ids: uniq(values.acquaintIds, ""),
  };
}

export function toDraftBody(values: OfficeValues): ResolutionDraftIn {
  const executor = needsExecutor(values.kind);
  return {
    kind: values.kind || null,
    responsible_id: executor && values.responsibleId ? values.responsibleId : null,
    due: executor && values.due ? values.due : null,
    text: values.text.trim() || null,
    co_executor_ids: executor ? uniq(values.coIds, values.responsibleId) : [],
    acquaint_ids: uniq(values.acquaintIds, ""),
  };
}

/** Проект целиком как тело резолюции — «Утвердить» одним нажатием; неполный проект (нет типа, текста, исполнителя) — `null`. */
export function draftAsResolution(
  letter: Pick<LetterCard, "resolution_draft">,
  today: string,
): OfficeResolutionIn | null {
  const draft = letter.resolution_draft;
  if (!draft?.kind) return null;
  const values: OfficeValues = {
    kind: draft.kind,
    responsibleId: draft.responsible?.id ?? "",
    due: draft.due ?? "",
    text: draft.text ?? "",
    templated: false,
    coIds: draft.co_executors.map((p) => p.id),
    acquaintIds: draft.acquaint.map((p) => p.id),
  };
  return Object.keys(validateOffice(values, today)).length === 0 ? toOfficeBody(values) : null;
}
