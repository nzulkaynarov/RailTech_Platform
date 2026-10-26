import type { AuditActorType, AuditEntry } from "../../shared/api/generated/model";

/**
 * Журнал аудита для MSW (Admin · Журнал аудита, W13-A6). Вымышленные записи в духе CRM: коды `action` и `entity_type` — как
 * в CRM, `before`/`after` — как их пишет аудит. Хранится в `localStorage` страницы (как сессия мока); новые записи
 * (выдача ролей, роли, сброс пароля) дописывает `recordAudit`. Новые записи первыми. Без хранилища — копия в памяти.
 */
const KEY = "rt-pf-mock-audit";

const ADMIN = { actor_id: "u-demo-admin", actor_name: "Демо Админов" };
const DIRECTOR = { actor_id: "u-demo-director", actor_name: "Демо Директоров" };

const MANAGER_BEFORE = {
  name: "Менеджер",
  description: "Лиды, клиенты и заявки; переписка с клиентом.",
  access: { "crm.leads": "full", "crm.clients": "full" },
  restricted_fields: [],
};
const MANAGER_AFTER = {
  ...MANAGER_BEFORE,
  access: {
    "crm.leads": "full",
    "crm.clients": "full",
    "erp.calc": "read",
    "chats.external": "read",
  },
  restricted_fields: ["supplier_prices"],
};

function entry(
  id: number,
  at: string,
  who: { actor_id: string; actor_name: string } | null,
  action: string,
  entityType: string,
  entityId: string | undefined,
  extra: Partial<AuditEntry> = {},
  actorType: AuditActorType = who ? "user" : "system",
): AuditEntry {
  return {
    id: String(id),
    at,
    actor_type: actorType,
    ...(who ? who : {}),
    action,
    entity_type: entityType,
    ...(entityId ? { entity_id: entityId } : {}),
    ...(who ? { ip: "10.20.0.12" } : {}),
    ...extra,
  };
}

export function seedAudit(): AuditEntry[] {
  return [
    entry(120, "2026-10-26T09:42:00Z", ADMIN, "user.reset_password_email", "user", "u-demo-supply"),
    entry(119, "2026-10-26T08:15:00Z", ADMIN, "integrations.smtp", "integration_secret", "smtp", {
      before: { host: "smtp.old.example", password_last4: "ab12" },
      after: { host: "smtp.demo.example", password_last4: "9f3c" },
    }),
    entry(118, "2026-10-25T14:03:00Z", ADMIN, "user.update", "user", "u-demo-manager", {
      before: { platform_role_names: ["Менеджер"], position: "Менеджер по продажам" },
      after: { platform_role_names: ["Менеджер", "Снабженец"], position: "Менеджер по продажам" },
    }),
    entry(117, "2026-10-25T11:20:00Z", DIRECTOR, "settings.update", "settings", undefined, {
      before: { "business_hours.start": "09:00" },
      after: { "business_hours.start": "08:30" },
    }),
    entry(116, "2026-10-24T16:48:00Z", ADMIN, "platform_role.update", "platform_role", "3", {
      before: MANAGER_BEFORE,
      after: MANAGER_AFTER,
    }),
    entry(115, "2026-10-24T10:05:00Z", ADMIN, "user.invite", "user", "u-demo-invited"),
    entry(114, "2026-10-24T10:04:00Z", ADMIN, "user.create", "user", "u-demo-invited", {
      after: { email: "invited@demo.example", full_name: "Демо Приглашённая", is_active: true },
    }),
    entry(
      113,
      "2026-10-23T18:30:00Z",
      null,
      "client.erp_handoff_done",
      "client",
      "L-2041",
      {},
      "bot",
    ),
    entry(
      112,
      "2026-10-23T09:12:00Z",
      ADMIN,
      "external_service.disable",
      "external_service",
      "dadata",
    ),
    entry(111, "2026-10-23T06:20:00Z", ADMIN, "platform_role.create", "platform_role", "3", {
      after: MANAGER_BEFORE,
    }),
    entry(110, "2026-10-22T12:00:00Z", ADMIN, "model.update", "model", "dialog", {
      before: { model: "gpt-small" },
      after: { model: "gpt-medium" },
    }),
    entry(109, "2026-10-22T07:45:00Z", null, "system.backup_requested", "system", undefined),
    entry(108, "2026-10-21T15:10:00Z", ADMIN, "auth.login", "user", "u-demo-admin"),
    entry(107, "2026-10-21T09:02:00Z", DIRECTOR, "auth.login", "user", "u-demo-director"),
    entry(106, "2026-10-20T13:37:00Z", ADMIN, "user.update", "user", "u-demo-accountant", {
      before: { is_active: true },
      after: { is_active: false },
    }),
  ];
}

let memory: AuditEntry[] | null = null;

export function readAudit(): AuditEntry[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as AuditEntry[]) : seedAudit();
  } catch {
    memory ??= seedAudit();
    return memory;
  }
}

export function writeAudit(items: AuditEntry[]): void {
  memory = items;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetAudit(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

export interface AuditDraft {
  action: string;
  entityType: string;
  entityId?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}

/** Дописывает запись от имени сотрудника сессии (новая — первой). */
export function recordAudit(who: { id: string; name: string } | null, draft: AuditDraft): void {
  const items = readAudit();
  const id = Math.max(0, ...items.map((e) => Number(e.id))) + 1;
  const next = entry(
    id,
    new Date().toISOString(),
    who ? { actor_id: who.id, actor_name: who.name } : null,
    draft.action,
    draft.entityType,
    draft.entityId,
    {
      ...(draft.before ? { before: draft.before } : {}),
      ...(draft.after ? { after: draft.after } : {}),
    },
  );
  writeAudit([next, ...items]);
}
