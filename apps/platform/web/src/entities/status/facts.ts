import type {
  IntegrationCardKey,
  IntegrationsOverview,
  SetupStep,
  SetupStepKey,
  StatusFact,
  StatusState,
} from "../../shared/api/generated/model";

/**
 * Одна функция на один факт (НАСТ-П1, аудит Настроек §6.2 п. 4): строка «Состояния», карточка «Сервисов», шаг мастера и
 * счётчик готовности берут слово состояния отсюда — из `fact` карточки ответа BFF. Тут слово не придумывается: BFF
 * решает, «Работает» или нет (`bff/app/status_model.py`); экран только читает.
 */

/** Нет ответа или нет такой карточки — «Не удалось проверить», не «Работает» и не «Нет данных». */
export const UNKNOWN_FACT: StatusFact = {
  state: "unknown",
  checked_at: null,
  source: "none",
  live: false,
};

export function cardFact(
  overview: IntegrationsOverview | undefined,
  key: IntegrationCardKey,
): StatusFact {
  return overview?.cards.find((card) => card.key === key)?.fact ?? UNKNOWN_FACT;
}

/** Какая карточка «Сервисов» проверяет шаг первого запуска; у шагов без карточки проверки связи нет. */
export const STEP_CARD: Partial<Record<SetupStepKey, IntegrationCardKey>> = {
  erp: "erp",
  bot: "telegram",
  mail: "mail",
  models: "models",
};

/** Состояние шага: сделан без проверки связи (`done`), работает (`works`) или слово из проверки службы. */
export type StepVerdict = "works" | "done" | "todo" | Exclude<StatusState, "works" | "off">;

/**
 * Шаг мастера: «Готово» ставит сам шаг (настройки сохранены), «Работает» — только проверка службы. Шаг с карточкой,
 * сохранённый, но не работающий, получает слово карточки; ответа нет — «Не удалось проверить».
 */
export function stepVerdict(
  step: SetupStep["state"],
  fact: StatusFact | undefined,
  hasCard: boolean,
): StepVerdict {
  if (step === "todo") return "todo";
  if (step === "unknown") return "unknown";
  if (!hasCard) return "done";
  const state = (fact ?? UNKNOWN_FACT).state;
  if (state === "works") return "works";
  return state === "off" ? "not_verified" : state;
}

/** В счётчик «готово N из M» входят только `works` и `done`: сохранённое, но не работающее — не готово. */
export function isReady(verdict: StepVerdict): boolean {
  return verdict === "works" || verdict === "done";
}

/** Слова из проверки службы: после них — слово «Работает» не стоит. */
export function claimsWorking(state: StatusState): boolean {
  return state === "works";
}
