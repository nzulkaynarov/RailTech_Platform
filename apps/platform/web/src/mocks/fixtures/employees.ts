import type { Employee } from "../../shared/api/generated/model";
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
  telegram: boolean;
  status?: Employee["status"];
}

const SEEDS: readonly Seed[] = [
  { id: "u-demo-manager", telegram: true },
  { id: "u-demo-director", telegram: true },
  { id: "u-demo-supply", telegram: false },
  { id: "u-demo-engineer", telegram: false },
  { id: "u-demo-accountant", telegram: true },
  { id: "u-demo-admin", telegram: true },
  { id: "u-demo-all", telegram: false },
  { id: "u-demo-new", telegram: false, status: "invited" },
  { id: "u-demo-disabled", telegram: false, status: "disabled" },
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
      telegram_linked: seed.telegram,
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
  return { ...rest, roles: rolesOf(roleIds, readRoles()).map(roleRefOf) };
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
