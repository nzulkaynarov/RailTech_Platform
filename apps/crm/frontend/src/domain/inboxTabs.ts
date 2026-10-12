/**
 * Вкладки «Входящих» (UX волна 2): один список вместо четырёх колонок. Вкладка — в URL (`?tab=`);
 * без неё открывается первая непустая в порядке очереди, чтобы менеджер сразу видел работу.
 */
export const INBOX_TABS = ["handoffs", "mine", "unassigned", "requests"] as const;
export type InboxTab = (typeof INBOX_TABS)[number];

export type InboxCounts = Partial<Record<InboxTab, number | undefined>>;

const isTab = (value: string | null): value is InboxTab =>
  value !== null && (INBOX_TABS as readonly string[]).includes(value);

/**
 * Какая вкладка открыта: из URL, если она доступна роли; иначе первая непустая; иначе первая.
 * `available` — вкладки, которые роль видит («Запросы клиентов» — только с правом на клиентов).
 */
export function pickInboxTab(
  param: string | null,
  counts: InboxCounts,
  available: readonly InboxTab[] = INBOX_TABS,
): InboxTab {
  if (isTab(param) && available.includes(param)) return param;
  return available.find((tab) => (counts[tab] ?? 0) > 0) ?? available[0] ?? "handoffs";
}
