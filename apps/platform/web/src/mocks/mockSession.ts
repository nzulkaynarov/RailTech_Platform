import type { Language, Me, RoleCode, Session } from "../shared/api/generated/model";
import { effectiveRoles } from "./fixtures/employees";
import { computeAccess } from "./fixtures/rbac";
import { type DemoUser, DEMO_USERS } from "./fixtures/users";

/**
 * Сессия MSW-мока. Хранится в `localStorage` страницы (обработчики MSW работают в потоке страницы), поэтому
 * переживает перезагрузку, как настоящая cookie; без хранилища — в памяти. Только для моков и тестов.
 */
const KEY = "rt-pf-mock-session";

interface MockSession {
  userId: string;
  activeRole: RoleCode | null;
  language: Language;
  mustChangePassword: boolean;
}

let memory: MockSession | null = null;

export function readSession(): MockSession | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as MockSession) : null;
  } catch {
    return memory;
  }
}

export function writeSession(session: MockSession | null): void {
  memory = session;
  try {
    if (session) window.localStorage.setItem(KEY, JSON.stringify(session));
    else window.localStorage.removeItem(KEY);
  } catch {
    // Остаётся копия в памяти.
  }
}

export function startSession(user: DemoUser): MockSession {
  const session: MockSession = {
    userId: user.id,
    activeRole: null,
    language: user.language,
    mustChangePassword: user.mustChangePassword ?? false,
  };
  writeSession(session);
  setCookie("rt_pf_csrf", "mock-csrf-token-0123456789abcdef");
  return session;
}

export function endSession(): void {
  writeSession(null);
  setCookie("rt_pf_csrf", "", 0);
}

function setCookie(name: string, value: string, maxAge = 60 * 60 * 12): void {
  try {
    document.cookie = `${name}=${value}; path=/; max-age=${String(maxAge)}; samesite=lax`;
  } catch {
    // Cookie недоступны — моки CSRF не проверяют.
  }
}

/** `Me` для сессии: при выбранной активной роли модули и разделы считаются по ней одной, иначе — по объединению ролей. */
export function buildMe(session: MockSession): Me | undefined {
  const user = DEMO_USERS.find((u) => u.id === session.userId);
  if (!user) return undefined;
  // Роли — с учётом выданных в Admin · Оргструктуре (мок хранит их в `fixtures/employees`).
  const roles = effectiveRoles(user.id, user.roles);
  const effective =
    session.activeRole && roles.includes(session.activeRole) ? [session.activeRole] : roles;
  const computed = computeAccess(effective);
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    initials: user.initials,
    position: user.position,
    language: session.language,
    roles,
    active_role:
      session.activeRole && roles.includes(session.activeRole) ? session.activeRole : null,
    modules: computed.modules,
    resources: computed.resources,
    restricted_fields: computed.restricted_fields,
    access: computed.access,
  };
}

export function buildSession(session: MockSession): Session | undefined {
  const me = buildMe(session);
  if (!me) return undefined;
  return {
    me,
    must_change_password: session.mustChangePassword,
    expires_at: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
  };
}

export function updateSession(patch: Partial<MockSession>): MockSession | null {
  const current = readSession();
  if (!current) return null;
  const next = { ...current, ...patch };
  writeSession(next);
  return next;
}
