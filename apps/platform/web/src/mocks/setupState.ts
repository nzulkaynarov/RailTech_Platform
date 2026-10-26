import type { SetupStepKey } from "../shared/api/generated/model";

/**
 * Состояние «Первого запуска» для MSW (W13-A4). По умолчанию система настроена: администратор есть, все шаги чек-листа
 * сделаны, компания создана — баннер не показывается и остальные сценарии не меняются. Сценарий «чистая установка»
 * включает `startFreshInstall` (тесты) или запись в `localStorage` до загрузки страницы (e2e): администратора нет, шаги не
 * сделаны. Хранится в `localStorage` страницы (как сессия мока), без хранилища — в памяти. Код первого запуска и пароли в
 * моках — только те, что задал тест.
 */
const KEY = "rt-pf-mock-setup";

export interface SetupMock {
  /** В CRM ещё нет администратора */
  needsAdmin: boolean;
  /** Ожидаемый код первого запуска (задаёт тест) */
  code: string;
  /** Чистая установка: шаги чек-листа считаются по `done`, а не «всё сделано» */
  fresh: boolean;
  companyCreated: boolean;
  done: Partial<Record<SetupStepKey, boolean>>;
}

const DEFAULTS: SetupMock = {
  needsAdmin: false,
  code: "",
  fresh: false,
  companyCreated: true,
  done: {},
};

let memory: SetupMock | null = null;

export function readSetup(): SetupMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<SetupMock>) } : (memory ?? DEFAULTS);
  } catch {
    return memory ?? DEFAULTS;
  }
}

export function writeSetup(state: SetupMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetSetup(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

/** Чистая установка: администратора нет, нужен код `code`, шаги не сделаны, компании нет. */
export function startFreshInstall(code: string): void {
  writeSetup({ needsAdmin: true, code, fresh: true, companyCreated: false, done: {} });
}

/** Уже есть администратор, но настройка не начата: шаги не сделаны, компании нет. */
export function startFreshSetup(): void {
  writeSetup({ needsAdmin: false, code: "", fresh: true, companyCreated: false, done: {} });
}

export function markStepDone(step: SetupStepKey): void {
  const state = readSetup();
  if (state.fresh) writeSetup({ ...state, done: { ...state.done, [step]: true } });
}
