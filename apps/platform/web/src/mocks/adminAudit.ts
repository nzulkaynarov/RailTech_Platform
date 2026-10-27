import { HttpResponse, http } from "msw";

import type {
  NotificationSettingsUpdate,
  RoleChange,
  RoleSnapshot,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { readAudit, recordAudit } from "./fixtures/audit";
import { readEmployees } from "./fixtures/employees";
import { currentActor, readSession, sessionRoles } from "./mockSession";

/**
 * Моки W13-A6: `GET /admin/audit`, `GET /admin/roles/:id/journal`, `POST /admin/users/:id/reset-password/email`,
 * `/me/notification-settings`, `/me/test-notification`. Журнал — раздел `admin` от чтения (директор читает), сброс пароля —
 * `admin: full`; профиль доступен каждому вошедшему. Входы по умолчанию скрыты, как у BFF.
 */
const LOGIN_PREFIXES = ["auth.login", "sso.exchange"];

const NOTIFY_KEY = "rt-pf-mock-notify";
interface MockNotify {
  notify_leads: boolean;
  notify_system: boolean;
  delivery_failed_at?: string;
}

function readNotify(userId: string): MockNotify {
  try {
    const raw = window.localStorage.getItem(`${NOTIFY_KEY}-${userId}`);
    if (raw) return JSON.parse(raw) as MockNotify;
  } catch {
    // Хранилище недоступно — значения по умолчанию.
  }
  // У бухгалтера демонстрируется «доставка не удалась»: так виден путь «нажмите Старт».
  return userId === "u-demo-accountant"
    ? { notify_leads: true, notify_system: false, delivery_failed_at: "2026-10-25T10:00:00Z" }
    : { notify_leads: true, notify_system: false };
}

function writeNotify(userId: string, value: MockNotify): void {
  try {
    window.localStorage.setItem(`${NOTIFY_KEY}-${userId}`, JSON.stringify(value));
  } catch {
    // Остаётся значение по умолчанию.
  }
}

function currentUserId(): string | null {
  const session = readSession();
  return session ? (sessionRoles(session)?.user.id ?? null) : null;
}

const telegramLinked = (userId: string) =>
  readEmployees().find((e) => e.id === userId)?.telegram_linked ?? false;

const asSnapshot = (value: unknown): RoleSnapshot | undefined =>
  value && typeof value === "object" && "access" in value ? (value as RoleSnapshot) : undefined;

export const adminAuditHandlers = [
  http.get("*/admin/audit", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const q = new URL(request.url).searchParams;
    const limit = Number(q.get("limit") ?? 50);
    const offset = Number(q.get("offset") ?? 0);
    const from = q.get("from");
    const to = q.get("to");
    const showLogins = q.get("include_logins") === "true";
    const rows = readAudit()
      .filter((e) => showLogins || !LOGIN_PREFIXES.some((p) => e.action.startsWith(p)))
      .filter((e) => !q.get("actor_id") || e.actor_id === q.get("actor_id"))
      .filter((e) => !q.get("action") || e.action.startsWith(q.get("action") ?? ""))
      .filter((e) => !q.get("entity_type") || e.entity_type === q.get("entity_type"))
      .filter((e) => !q.get("entity_id") || e.entity_id === q.get("entity_id"))
      .filter((e) => !from || new Date(e.at) >= new Date(from))
      .filter((e) => !to || new Date(e.at) < new Date(to));
    return HttpResponse.json({
      items: rows.slice(offset, offset + limit),
      total: rows.length,
      limit,
      offset,
    });
  }),

  http.get("*/admin/roles/:id/journal", ({ params, request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const q = new URL(request.url).searchParams;
    const limit = Number(q.get("limit") ?? 50);
    const offset = Number(q.get("offset") ?? 0);
    const rows = readAudit().filter(
      (e) => e.entity_type === "platform_role" && e.entity_id === params["id"],
    );
    const items: RoleChange[] = rows.slice(offset, offset + limit).map((e) => {
      const before = asSnapshot(e.before);
      const after = asSnapshot(e.after);
      return {
        id: e.id,
        at: e.at,
        action: e.action.split(".").pop() as RoleChange["action"],
        ...(e.actor_id ? { actor_id: e.actor_id } : {}),
        ...(e.actor_name ? { actor_name: e.actor_name } : {}),
        ...(before ? { before } : {}),
        ...(after ? { after } : {}),
      };
    });
    return HttpResponse.json({ items, total: rows.length });
  }),

  http.post("*/admin/users/:id/reset-password/email", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const id = String(params["id"]);
    if (id === currentUserId()) {
      return failure(
        409,
        "CONFLICT",
        "Свой пароль здесь не сбросить: выберите «Сменить пароль» в меню аватара.",
        "bff",
        { reason: "self_reset" },
      );
    }
    const employee = readEmployees().find((e) => e.id === id);
    if (!employee) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    // Адрес nomail@ показывает путь «почта не подключена»: пароль не меняется.
    if (employee.email.startsWith("nomail@")) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "smtp_not_configured",
      });
    }
    recordAudit(currentActor(), {
      action: "user.reset_password_email",
      entityType: "user",
      entityId: id,
    });
    return HttpResponse.json({ email_log_id: 41, status: "queued", to_email: employee.email });
  }),

  http.get("*/me/notification-settings", () => {
    const userId = currentUserId();
    if (!userId) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    return HttpResponse.json({ telegram_linked: telegramLinked(userId), ...readNotify(userId) });
  }),

  http.patch("*/me/notification-settings", async ({ request }) => {
    const userId = currentUserId();
    if (!userId) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const body = (await request.json()) as NotificationSettingsUpdate;
    const next = { ...readNotify(userId), ...body };
    writeNotify(userId, next);
    return HttpResponse.json({ telegram_linked: telegramLinked(userId), ...next });
  }),

  http.post("*/me/test-notification", () => {
    const userId = currentUserId();
    if (!userId) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!telegramLinked(userId)) {
      return failure(409, "CONFLICT", "Telegram не привязан.", "crm", {
        reason: "telegram_not_linked",
      });
    }
    // Успешная доставка снимает предупреждение «сообщение не дошло».
    const current = readNotify(userId);
    writeNotify(userId, {
      notify_leads: current.notify_leads,
      notify_system: current.notify_system,
    });
    return new HttpResponse(null, { status: 204 });
  }),
];
