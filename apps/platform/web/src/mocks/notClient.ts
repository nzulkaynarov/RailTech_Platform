import type {
  CabinetTruth,
  CounterpartyRoleState,
  NotClientPlan,
} from "../shared/api/generated/model";

/**
 * «Не клиент» на моках (КОНТР-1б): компании клиентов CRM, у которых сотрудник снял роль клиента. Список клиентов и
 * карточка читают роли отсюда — тот же источник, что у ERP (`portal.desk.company_roles`).
 */
const CLIENT_BASE = 1000;
const removed = new Set<string>();

/** Клиент 3 — с настоящей историей (КП отправлены, договор): снятие роли предупреждает; остальные — без вопросов. */
const WITH_HISTORY = new Set([CLIENT_BASE + 3]);

export function isNotClient(companyId: string): boolean {
  return removed.has(companyId);
}

export function markNotClient(companyId: string): void {
  removed.add(companyId);
}

export function resetNotClient(): void {
  removed.clear();
}

/** Роли компании клиента CRM: клиент, пока роль не снята; партнёрской роли у мок-клиентов нет. */
export function roleStatesOf(companyId: string): CounterpartyRoleState[] {
  return removed.has(companyId) ? [] : [{ role: "client", state: "active", kind: null }];
}

export function cabinetOf(companyId: string): CabinetTruth {
  const client = !removed.has(companyId);
  return {
    opened: client,
    roles: client ? ["client"] : [],
    sees: client ? "client" : "none",
    last_login_at: client ? "2026-11-25T08:22:00Z" : null,
    logged_in_contacts: client ? 1 : 0,
  };
}

export function planOf(companyId: string, dryRun: boolean): NotClientPlan {
  const id = Number(companyId);
  const history = WITH_HISTORY.has(id);
  return {
    company_id: companyId,
    dry_run: dryRun,
    is_client: !removed.has(companyId),
    requests_to_close: history ? [] : ["RQ-2026-009"],
    requests_kept: history ? ["RQ-2026-004"] : [],
    history: history
      ? { quotes_sent: 2, contracts: 1, invoices: 1, projects: 0 }
      : { quotes_sent: 0, contracts: 0, invoices: 0, projects: 0 },
    has_history: history,
    contacts: 1,
    contacts_with_cabinet: 1,
    remaining_roles: [],
    requests_closed: dryRun || history ? [] : ["RQ-2026-009"],
    candidate_entry: false,
  };
}
