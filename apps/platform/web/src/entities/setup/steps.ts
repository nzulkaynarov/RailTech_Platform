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
  bot: "/admin/telegram",
  erp: "/admin/integrations?card=erp&panel=open",
  mail: "/admin/mail",
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
 * Нужен ли баннер: есть несделанный шаг, в ERP ещё нет своей компании или у неё нет реквизитов для счетов. Шаг «нет данных» сам по себе баннер не
 * показывает: бэкенд не ответил, и подталкивать к действию без причины нельзя.
 */
export function needsSetup(checklist: SetupChecklist): boolean {
  return (
    nextStep(checklist) !== undefined ||
    checklist.company?.required === true ||
    bankDetailsMissing(checklist)
  );
}

/**
 * Где администратор вводит р/с и МФО своей компании (D26G-6): «Настройки · Реквизиты и бланк» (SET-IA), сразу секция
 * «Банковские счета» (реквизиты — секциями, platform-frontend.md §4.1a).
 */
export const BANK_DETAILS_PATH = "/admin/company?section=bank";

/**
 * Своя компания есть, а банковских реквизитов для счетов нет (D26G-6, признак ERP — та же проверка, что «Выставить
 * счёт»): шаг мастера не сделан, баннер остаётся — без них первый счёт клиенту не выставить.
 */
export function bankDetailsMissing(checklist: SetupChecklist): boolean {
  return checklist.company?.required === false && !checklist.company.bank_details_ready;
}

/**
 * После шага ERP мастер остаётся на «Ваша компания», пока компании нет (нужна форма) или ERP ещё не выдала доступ
 * (данных о компании нет, `erp_unavailable`: ~12 с после сопряжения) — W15-G-10. Иначе он уходил к шагу «Telegram-бот»,
 * и компания оставалась «Нет данных».
 */
export function staysOnCompany(checklist: SetupChecklist): boolean {
  return (
    checklist.company?.required === true ||
    (checklist.company === null && checklist.company_blocker === "erp_unavailable")
  );
}

/**
 * Шаги, которые мастер показывает (СЦ-3): счётчик «готово N из M», «Дальше: …» и «Шаг N из M» считаются по этому же
 * списку, а не по пяти ключам чек-листа BFF — иначе «готово 3 из 5» при пяти «Готово» на экране и «Дальше» к шагу ниже.
 */
export type VisibleKey =
  | "admin"
  | "erp"
  | "company"
  | "bank"
  | "cabinet"
  | "bot"
  | "mail"
  | "models"
  | "first_employee"
  | "signing";

export const VISIBLE_ORDER: readonly VisibleKey[] = [
  "admin",
  "erp",
  "company",
  "bank",
  "cabinet",
  "bot",
  "mail",
  "models",
  "first_employee",
  "signing",
];

export interface VisibleStep {
  key: VisibleKey;
  state: SetupStep["state"];
  /** Куда ведёт «Дальше» и строка шага: сам шаг, а не начало мастера */
  to: string;
}

export const SIGNING_PATH = "/admin/signing";

/**
 * Состояние каждого видимого шага. `cabinetUrl` — `undefined`, пока адрес кабинета не загружен; `signing` — `undefined`,
 * если у сотрудника нет права выдавать полномочия подписи или ответ ещё не пришёл: строки «Права подписи» тогда нет.
 */
export function visibleSteps(
  c: SetupChecklist,
  extra: { cabinetUrl?: string | null; signing?: boolean },
): VisibleStep[] {
  const fromChecklist = (key: SetupStepKey): VisibleStep => ({
    key,
    state: c.steps.find((s) => s.key === key)?.state ?? "unknown",
    to: STEP_TARGET[key],
  });
  const company: VisibleStep["state"] =
    c.company === null ? "unknown" : c.company.required ? "todo" : "done";
  const bank: VisibleStep["state"] =
    c.company === null
      ? "unknown"
      : c.company.required || !c.company.bank_details_ready
        ? "todo"
        : "done";
  const cabinet: VisibleStep["state"] =
    extra.cabinetUrl === undefined ? "unknown" : extra.cabinetUrl ? "done" : "todo";
  const steps: VisibleStep[] = [
    { key: "admin", state: "done", to: WIZARD_PATH },
    fromChecklist("erp"),
    { key: "company", state: company, to: WIZARD_PATH },
    { key: "bank", state: bank, to: BANK_DETAILS_PATH },
    { key: "cabinet", state: cabinet, to: WIZARD_PATH },
    fromChecklist("bot"),
    fromChecklist("mail"),
    fromChecklist("models"),
    fromChecklist("first_employee"),
  ];
  if (extra.signing !== undefined) {
    steps.push({ key: "signing", state: extra.signing ? "done" : "todo", to: SIGNING_PATH });
  }
  return steps;
}

export function progress(steps: readonly VisibleStep[]): {
  done: number;
  total: number;
  next: VisibleStep | undefined;
} {
  return {
    done: steps.filter((s) => s.state === "done").length,
    total: steps.length,
    next: steps.find((s) => s.state === "todo"),
  };
}

/** Ключ названия видимого шага в словаре `modules` (одно название в баннере, мастере и чек-листе Настроек). */
export function visibleTitleKey(key: VisibleKey): string {
  switch (key) {
    case "admin":
      return "admin.setup.adminTitle";
    case "company":
      return "admin.setup.companyTitle";
    case "bank":
      return "admin.setup.bankTitle";
    case "cabinet":
      return "admin.setup.cabinetTitle";
    case "signing":
      return "admin.setup.signing.title";
    default:
      return `admin.setup.steps.${key}.title`;
  }
}
