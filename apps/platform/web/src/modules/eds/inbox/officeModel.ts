import type {
  LetterCard,
  LetterResolutionKind,
  OfficeResolutionIn,
  ResolutionDraftIn,
  ResolutionTemplate,
  ResolutionTemplateIn,
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

// --- Шаблоны резолюций (EDS-REG, R2): «Из шаблона» заполняет форму, «Сохранить как шаблон» берёт её ---------------

const DAY_MS = 24 * 60 * 60 * 1000;

/** Дата `YYYY-MM-DD` через `days` дней; суббота и воскресенье — на понедельник (как подсказка срока EDS). */
export function dueIn(today: string, days: number): string {
  const at = new Date(`${today}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() + days);
  const weekday = at.getUTCDay();
  if (weekday === 6) at.setUTCDate(at.getUTCDate() + 2);
  if (weekday === 0) at.setUTCDate(at.getUTCDate() + 1);
  return at.toISOString().slice(0, 10);
}

/** Сколько дней от `today` до `due` (не меньше 1); пусто — `null`. */
export function daysUntil(today: string, due: string): number | null {
  if (!due) return null;
  const days = Math.round(
    (Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / DAY_MS,
  );
  return Math.min(365, Math.max(1, days));
}

/**
 * Применить шаблон: вид, текст, люди и срок из шаблона, ответственный «адресат» — адресат письма. Срок шаблона не задан —
 * подсказка срока письма. Форму потом можно поправить: шаблон только заполняет.
 */
export function applyTemplate(
  template: ResolutionTemplate,
  letter: Pick<LetterCard, "addressee" | "suggested_due">,
  today: string,
): OfficeValues {
  const executor = needsExecutor(template.kind);
  const responsibleId =
    template.responsible_type === "person"
      ? (template.responsible?.id ?? "")
      : template.responsible_type === "addressee"
        ? letter.addressee.id
        : "";
  return {
    kind: template.kind,
    text: template.text,
    templated: false,
    responsibleId: executor ? responsibleId : "",
    due: executor
      ? template.due_days
        ? dueIn(today, template.due_days)
        : (letter.suggested_due ?? "")
      : "",
    coIds: executor ? template.co_executors.map((p) => p.id) : [],
    acquaintIds: template.acquaint.map((p) => p.id),
  };
}

/** Тело «Сохранить как шаблон» из формы: ответственный — сотрудник или «выбрать при резолюции», срок — в днях от сегодня. */
export function templateFromForm(
  values: OfficeValues,
  name: string,
  scope: ResolutionTemplateIn["scope"],
  today: string,
): ResolutionTemplateIn {
  const executor = needsExecutor(values.kind);
  const responsible = executor && values.responsibleId ? values.responsibleId : null;
  return {
    name: name.trim(),
    scope,
    kind: values.kind || "execute",
    text: values.text.trim(),
    responsible_type: responsible ? "person" : "none",
    responsible_id: responsible,
    co_executor_ids: executor ? uniq(values.coIds, values.responsibleId) : [],
    acquaint_ids: uniq(values.acquaintIds, ""),
    due_days: executor ? daysUntil(today, values.due) : null,
  };
}
