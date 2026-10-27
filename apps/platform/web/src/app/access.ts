import type { AccessLevel, Me } from "../shared/api/generated/model";
import { findModule } from "../modules/registry";
import type { AccessRule } from "../modules/types";
import { DEFAULT_HOME } from "./auth/redirect";

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
  const level = levelForRule(me, rule);
  if (level === undefined) return false;
  return rule.level === undefined || RANK[level] >= RANK[rule.level];
}

export function canEdit(me: Me, resource: string): boolean {
  return levelOf(me, resource) === "full";
}

/**
 * Куда вести сотрудника после входа: «Моя очередь», если она есть у ролей, иначе первый доступный раздел первого модуля
 * рейла (ADR-0012: роль без Dashboard — например, «Менеджер и бухгалтер» — не должна упираться в «Нет доступа»).
 */
export function homePath(me: Me): string {
  if (canSee(me, { resource: "dashboard.queue" })) return DEFAULT_HOME;
  for (const code of me.modules) {
    const section = findModule(code)?.sections.find((s) => !s.hidden && canSee(me, s.access));
    if (section) return section.path;
  }
  return DEFAULT_HOME;
}
