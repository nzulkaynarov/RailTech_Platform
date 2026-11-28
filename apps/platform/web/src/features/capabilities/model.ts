import type {
  CapabilityActionLevel,
  CapabilityLevel,
  CapabilityText,
  EmployeeCapabilities,
} from "../../shared/api/generated/model";

/** Уровни возможности по возрастанию: нет → смотреть → работать → решать (ДОСТ-1). */
export const LEVELS: readonly CapabilityLevel[] = ["none", "view", "work", "decide"];

/** Текст каталога на языке интерфейса; пустой — русский. */
export function pickText(text: CapabilityText, language: string): string {
  const lang = language.slice(0, 2) as keyof CapabilityText;
  return text[lang] || text.ru;
}

export function rank(level: CapabilityLevel): number {
  return LEVELS.indexOf(level);
}

const ACTION_LEVEL_FOR_ACCESS = { read: "view", full: "work" } as const;

export interface MissingCapability {
  key: string;
  name: CapabilityText;
  /** Уровень, который открывает раздел */
  needed: CapabilityActionLevel;
  /** Уровень сотрудника сейчас */
  current: CapabilityLevel;
}

/**
 * Какая возможность не выдана, если раздел `resource` закрыт на уровне `need`: первая строка каталога, у которой есть действие
 * с таким условием BFF («раздел:уровень»; через «|» — любое из). Уровень строки — уровень, в котором стоит это действие.
 * Не нашлась — `null`: экран говорит общими словами.
 */
export function findMissing(
  data: EmployeeCapabilities,
  keys: readonly string[],
  need: "read" | "full",
): MissingCapability | null {
  const wanted = new Set(keys.map((key) => `${key}:${need}`));
  // Сначала точное совпадение уровня, затем «полный» вместо «чтения» (читающий раздел может смотреть).
  const fallback = new Set(keys.map((key) => `${key}:full`));
  const hit = (gates: readonly string[], set: Set<string>) =>
    gates.some((gate) => gate.split("|").some((alt) => set.has(alt)));
  for (const set of [wanted, fallback]) {
    for (const group of data.groups) {
      for (const row of group.rows) {
        for (const level of row.levels) {
          if (level.actions.some((action) => hit(action.gates, set))) {
            return {
              key: row.key,
              name: row.name,
              needed: level.level,
              current: row.level,
            };
          }
        }
      }
    }
  }
  return null;
}

/** Нужный уровень по доступу раздела: чтение — «смотреть», изменение — «работать». */
export const levelForAccess = (need: "read" | "full"): CapabilityActionLevel =>
  ACTION_LEVEL_FOR_ACCESS[need];
