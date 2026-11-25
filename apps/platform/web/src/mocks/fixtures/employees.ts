import type { Employee } from "../../shared/api/generated/model";
import { avatarUrlOf, nameOf, readProfile } from "../profileStore";
import { ROLE_ID, readRoles, roleRefOf, rolesOf } from "./roles";
import { DEMO_USERS } from "./users";

/**
 * Сотрудники для MSW (Admin · Оргструктура, PLT-15, R-2). Вымышленные, домен `.example`. Хранятся в `localStorage`
 * страницы (как сессия мока) с id ролей: выданные в интерфейсе роли переживают перезагрузку и действуют при следующем
 * входе этого сотрудника (`effectiveRoleIds` подмешивается в `buildMe` мока сессии); названия ролей берутся из
 * хранилища ролей, поэтому переименование роли сразу видно в списке. Без хранилища — копия в памяти.
 */
const KEY = "rt-pf-mock-employees";

export type MockEmployee = Omit<Employee, "roles"> & { role_ids: string[] };

function accessFor(roleIds: readonly string[]): Employee["access"] {
  // R-1: непустые роли Платформы дают доступ к CRM и ERP; без ролей — только CRM.
  return { crm: true, erp: roleIds.length > 0 };
}

interface Seed {
  id: string;
  /** `blocked` — привязан, но бот не может писать («Старт» не нажат или бот заблокирован) */
  telegram: Employee["telegram"];
  status?: Employee["status"];
}

const SEEDS: readonly Seed[] = [
  { id: "u-demo-manager", telegram: "linked" },
  { id: "u-demo-director", telegram: "linked" },
  { id: "u-demo-supply", telegram: "not_linked" },
  { id: "u-demo-engineer", telegram: "not_linked" },
  { id: "u-demo-accountant", telegram: "blocked" },
  { id: "u-demo-admin", telegram: "linked" },
  { id: "u-demo-all", telegram: "not_linked" },
  { id: "u-demo-new", telegram: "not_linked", status: "invited" },
  { id: "u-demo-disabled", telegram: "not_linked", status: "disabled" },
];

function seedEmployees(): MockEmployee[] {
  const fromUsers = SEEDS.flatMap((seed) => {
    const user = DEMO_USERS.find((u) => u.id === seed.id);
    if (!user) return [];
    const roleIds = user.roles.map((code) => ROLE_ID[code]);
    const employee: MockEmployee = {
      id: user.id,
      name: user.name,
      initials: user.initials,
      email: user.email,
      ...(user.position && user.position !== "—" ? { position: user.position } : {}),
      role_ids: roleIds,
      access: accessFor(roleIds),
      status: seed.status ?? "active",
      telegram_linked: seed.telegram !== "not_linked",
      telegram: seed.telegram,
      erp_sync: "ok",
    };
    return [employee];
  });
  const invited: MockEmployee = {
    id: "u-demo-invited",
    name: "Демо Приглашённая",
    initials: "ДП",
    email: "invited@demo.example",
    position: "Инженер по проектам",
    role_ids: [ROLE_ID.ENGINEER],
    access: { crm: true, erp: true },
    status: "invited",
    telegram_linked: false,
    telegram: "not_linked",
    erp_sync: "pending",
  };
  return [...fromUsers, invited];
}

let memory: MockEmployee[] | null = null;

export function readEmployees(): MockEmployee[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as MockEmployee[]) : seedEmployees();
  } catch {
    // Хранилище недоступно — состояние живёт в памяти.
    memory ??= seedEmployees();
    return memory;
  }
}

export function writeEmployees(items: MockEmployee[]): void {
  memory = items;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetEmployees(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

/** Сотрудник в форме контракта: роли — ссылки с названиями из хранилища ролей (удалённые пропускаются). */
export function toEmployee(employee: MockEmployee): Employee {
  const { role_ids: roleIds, ...rest } = employee;
  // СУЩ-3: фото, загруженное в «Профиле», видно в списке; отключённому — инициалы, как в BFF
  const avatar = employee.status === "disabled" ? undefined : avatarUrlOf(employee.id);
  // Замещение хранится в профиле: его ставит сам сотрудник или администратор в карточке (СОТР-1)
  const stored = readProfile(employee.id).deputy;
  return {
    ...rest,
    ...(stored
      ? {
          deputy: {
            user_id: stored.id,
            name: nameOf(stored.id),
            date_from: stored.date_from,
            date_to: stored.date_to,
          },
        }
      : {}),
    roles: rolesOf(roleIds, readRoles()).map(roleRefOf),
    ...(avatar ? { avatar_url: avatar } : {}),
  };
}

/** Id ролей сотрудника с учётом выданного в Оргструктуре; нет записи — роли из `DEMO_USERS`. */
export function effectiveRoleIds(userId: string, fallback: readonly string[]): string[] {
  const employee = readEmployees().find((e) => e.id === userId);
  return employee ? [...employee.role_ids] : [...fallback];
}

/** Отключённый в Оргструктуре сотрудник входить не может (CRM отвечает как на неверный пароль). */
export function isEmployeeDisabled(userId: string): boolean {
  return readEmployees().find((e) => e.id === userId)?.status === "disabled";
}

export { accessFor };

/**
 * Сотрудники с ещё временным паролем (`must_change_password` в CRM): после включения они снова «Приглашён», а не «Активен».
 * Отключение статус «Приглашён» затирает, поэтому признак хранится отдельно.
 */
const PENDING_KEY = "rt-pf-mock-employees-pending";

export function readPendingPasswordIds(): string[] {
  try {
    const raw = window.localStorage.getItem(PENDING_KEY);
    if (raw) return JSON.parse(raw) as string[];
  } catch {
    // Хранилище недоступно — считаем по статусу в списке.
  }
  return readEmployees()
    .filter((e) => e.status === "invited")
    .map((e) => e.id);
}

export function writePendingPasswordIds(ids: string[]): void {
  try {
    window.localStorage.setItem(PENDING_KEY, JSON.stringify(ids));
  } catch {
    // Остаётся расчёт по статусу.
  }
}
