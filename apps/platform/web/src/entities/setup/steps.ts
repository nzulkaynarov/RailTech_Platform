import type { SetupChecklist, SetupStep, SetupStepKey } from "../../shared/api/generated/model";

/** Куда ведёт каждый шаг чек-листа (SPEC-v3 §7.6): карточка внешней интеграции или приглашение сотрудника. */
export const STEP_TARGET: Record<SetupStepKey, string> = {
  bot: "/admin/integrations?card=telegram&panel=open",
  erp: "/admin/integrations?card=erp&panel=open",
  mail: "/admin/integrations?card=mail&panel=open",
  models: "/admin/integrations?card=models&panel=open",
  first_employee: "/admin/org?invite=open&panel=open",
};

export const WIZARD_PATH = "/admin/setup";

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
