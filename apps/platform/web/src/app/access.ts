import type { AccessLevel, Me } from "../shared/api/generated/model";
import type { AccessRule } from "../modules/types";

const RANK: Record<AccessLevel, number> = { read: 1, full: 2 };

/** Уровень доступа к ресурсу матрицы; undefined — раздел скрыт (скрытые в `Me.resources` не перечисляются). */
export function levelOf(me: Me, resource: string): AccessLevel | undefined {
  return me.resources[resource];
}

/** Для правила «любой из» берётся максимум: full > read > скрыто (как объединение ролей в контракте). */
export function levelForRule(me: Me, rule: AccessRule): AccessLevel | undefined {
  const keys = "resource" in rule ? [rule.resource] : rule.anyOf;
  let best: AccessLevel | undefined;
  for (const key of keys) {
    const level = levelOf(me, key);
    if (level && (best === undefined || RANK[level] > RANK[best])) best = level;
  }
  return best;
}

export function canSee(me: Me, rule: AccessRule): boolean {
  return levelForRule(me, rule) !== undefined;
}

export function canEdit(me: Me, resource: string): boolean {
  return levelOf(me, resource) === "full";
}
