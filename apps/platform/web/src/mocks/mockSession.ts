import type { Language, Me, Session } from "../shared/api/generated/model";
import { effectiveRoleIds } from "./fixtures/employees";
import { ROLE_ID, computeAccess, readRoles, roleRefOf, rolesOf } from "./fixtures/roles";
import { type DemoUser, findUserById } from "./fixtures/users";
import { avatarUrlOf, initialsOf, nameOf, readProfile } from "./profileStore";

/**
 * Сессия MSW-мока. Хранится в `localStorage` страницы (обработчики MSW работают в потоке страницы), поэтому
 * переживает перезагрузку, как настоящая cookie; без хранилища — в памяти. Только для моков и тестов.
 */
const KEY = "rt-pf-mock-session";

interface MockSession {
  userId: string;
  /** Id активной роли («вид») */
  activeRole: string | null;
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

/** Роли сотрудника сессии (данные из хранилища ролей мока) и роли «вида» (активная, если задана). */
export function sessionRoles(session: MockSession) {
  const user = findUserById(session.userId);
  if (!user) return undefined;
  // Роли — с учётом выданных в Admin · Оргструктуре (мок хранит их в `fixtures/employees`).
  const ids = effectiveRoleIds(
    user.id,
    user.roles.map((code) => ROLE_ID[code]),
  );
  const all = rolesOf(ids, readRoles());
  const active = all.find((r) => r.id === session.activeRole);
  return { user, all, view: active ? [active] : all, active };
}

/** `Me` для сессии: при выбранной активной роли модули и разделы считаются по ней одной, иначе — по объединению ролей. */
export function buildMe(session: MockSession): Me | undefined {
  const roles = sessionRoles(session);
  if (!roles) return undefined;
  const { user, all, view, active } = roles;
  const computed = computeAccess(view);
  const avatar = avatarUrlOf(user.id);
  // Имя, которое сотрудник сменил на странице /me (W15-H6), и фото вместо инициалов.
  const name = nameOf(user.id) || user.name;
  return {
    id: user.id,
    email: user.email,
    name,
    initials: readProfile(user.id).name ? initialsOf(name) : user.initials,
    ...(avatar ? { avatar_url: avatar } : {}),
    position: user.position,
    language: session.language,
    roles: all.map(roleRefOf),
    active_role: active ? active.id : null,
    modules: computed.modules,
    resources: computed.resources as Me["resources"],
    restricted_fields: computed.restricted_fields,
    // R-1: роли Платформы дают доступ к CRM и ERP.
    access: { crm: true, erp: all.length > 0 },
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

/** Сотрудник текущей сессии мока — автор записей журнала аудита. */
export function currentActor(): { id: string; name: string } | null {
  const session = readSession();
  const user = session ? findUserById(session.userId) : undefined;
  return user ? { id: user.id, name: user.name } : null;
}
