import type { SetupChecklist, SetupStep, SetupStepKey } from "../../shared/api/generated/model";

export const WIZARD_PATH = "/admin/setup";

/** Порядок шагов в мастере: ERP первой (компания создаётся в ERP), затем остальные подключения и первый сотрудник. */
export const STEP_ORDER: readonly SetupStepKey[] = [
  "erp",
  "bot",
  "mail",
  "models",
  "first_employee",
];

export function isStepKey(value: string | null): value is SetupStepKey {
  return value !== null && (STEP_ORDER as readonly string[]).includes(value);
}

/**
 * Куда ведёт каждый шаг чек-листа (W15-H4, UX-оценка §5 P1-6): форма шага открывается в боковом окне самого мастера
 * (`?step=<шаг>`), без перехода на «Подключения» или «Сотрудников» и обратно.
 */
export const STEP_TARGET: Record<SetupStepKey, string> = Object.fromEntries(
  STEP_ORDER.map((key) => [key, `${WIZARD_PATH}?step=${key}&panel=open`]),
) as Record<SetupStepKey, string>;

/** Где тот же шаг настраивается после первого запуска (ссылка «Открыть в Настройках» в окне шага). */
export const STEP_HOME: Record<SetupStepKey, string> = {
  bot: "/admin/bot?part=connection",
  erp: "/admin/integrations?card=erp&panel=open",
  mail: "/admin/integrations?card=mail&panel=open",
  models: "/admin/integrations?card=models&panel=open",
  first_employee: "/admin/org",
};

/** Следующий несделанный шаг после `current` (по кругу не идём: раньше стоящие несделанные — тоже предлагаются). */
export function stepAfter(checklist: SetupChecklist, current: SetupStepKey): SetupStep | undefined {
  const todo = checklist.steps.filter((step) => step.state === "todo" && step.key !== current);
  const index = STEP_ORDER.indexOf(current);
  return (
    todo.find((step) => STEP_ORDER.indexOf(step.key) > index) ??
    todo.find((step) => STEP_ORDER.indexOf(step.key) < index)
  );
}

/** Первый шаг, который точно не сделан (`todo`); «нет данных» не считается — подгонять под него нечем. */
export function nextStep(checklist: SetupChecklist): SetupStep | undefined {
  return checklist.steps.find((step) => step.state === "todo");
}

/**
 * Нужен ли баннер: есть несделанный шаг или в ERP ещё нет своей компании. Шаг «нет данных» сам по себе баннер не
 * показывает: бэкенд не ответил, и подталкивать к действию без причины нельзя.
 */
export function needsSetup(checklist: SetupChecklist): boolean {
  return nextStep(checklist) !== undefined || checklist.company?.required === true;
}
