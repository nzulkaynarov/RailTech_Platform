import type { AttentionItem, ServiceGroup } from "../../../shared/api/generated/model";

const union = <T>(left: readonly T[], right: readonly T[]): T[] => [
  ...new Set([...left, ...right]),
];

function earliest(left: string | null, right: string | null): string | null {
  if (left === null) return right;
  if (right === null) return left;
  return left <= right ? left : right;
}

function mergeGroups(left: ServiceGroup, right: ServiceGroup): ServiceGroup {
  return {
    ...left,
    more_actions: union(left.more_actions, right.more_actions),
    affected: union(left.affected, right.affected),
    service_keys: union(left.service_keys, right.service_keys),
    titles: union(left.titles, right.titles),
    technical: [...left.technical, ...right.technical],
    since: earliest(left.since, right.since),
    flaps_24h: Math.max(left.flaps_24h, right.flaps_24h),
  };
}

/**
 * «Требует внимания» (S3, ресёрч 2026-11-02 «Настройки» §1.3): строки с одной и той же причиной — тот же текст «что
 * случилось и что сделать», та же важность, состояние, кто исправляет и главное действие — показываются одной строкой с
 * одной кнопкой: сервисы, затронутое и технические подробности объединяются, «с …» — самое раннее. «Проверить снова»
 * объединённой строки проверяет все её сервисы. Строки без группы и без текста причины не сливаются.
 */
export function mergeSameCause(items: readonly AttentionItem[]): AttentionItem[] {
  const result: AttentionItem[] = [];
  const byCause = new Map<string, number>();
  for (const item of items) {
    const group = item.group;
    if (group === null || group.detail === null) {
      result.push(item);
      continue;
    }
    const cause = [item.severity, group.state, group.owner, group.action, group.detail].join(
      "\u0000",
    );
    const at = byCause.get(cause);
    const kept = at === undefined ? undefined : result[at];
    if (kept?.group) {
      result[at as number] = { ...kept, group: mergeGroups(kept.group, group) };
      continue;
    }
    byCause.set(cause, result.length);
    result.push(item);
  }
  return result;
}
