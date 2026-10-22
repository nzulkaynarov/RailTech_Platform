import type { Employee, RoleCode } from "../../shared/api/generated/model";
import { DEMO_USERS } from "./users";

/**
 * Сотрудники для MSW (Admin · Оргструктура, PLT-15). Вымышленные, домен `.example`. Хранятся в `localStorage` страницы
 * (как сессия мока), поэтому выданные в интерфейсе роли переживают перезагрузку и действуют при следующем входе этого
 * сотрудника: `effectiveRoles` подмешивается в `buildMe` мока сессии. Без хранилища — копия в памяти.
 */
const KEY = "rt-pf-mock-employees";

function accessFor(roles: readonly RoleCode[]): Employee["access"] {
  // CRM-01: непустые роли Платформы дают доступ к CRM и ERP; без ролей — только CRM.
  return { crm: true, erp: roles.length > 0 };
}

interface Seed {
  id: string;
  telegram: boolean;
  status?: Employee["status"];
  erpSync?: Employee["erp_sync"];
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

function seedEmployees(): Employee[] {
  const fromUsers = SEEDS.flatMap((seed) => {
    const user = DEMO_USERS.find((u) => u.id === seed.id);
    if (!user) return [];
    const employee: Employee = {
      id: user.id,
      name: user.name,
      initials: user.initials,
      email: user.email,
      ...(user.position && user.position !== "—" ? { position: user.position } : {}),
      roles: [...user.roles],
      access: accessFor(user.roles),
      status: seed.status ?? "active",
      telegram_linked: seed.telegram,
      erp_sync: "ok",
    };
    return [employee];
  });
  const invited: Employee = {
    id: "u-demo-invited",
    name: "Демо Приглашённая",
    initials: "ДП",
    email: "invited@demo.example",
    position: "Инженер по проектам",
    roles: ["ENGINEER"],
    access: { crm: true, erp: true },
    status: "invited",
    telegram_linked: false,
    erp_sync: "pending",
  };
  return [...fromUsers, invited];
}

let memory: Employee[] | null = null;

export function readEmployees(): Employee[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Employee[]) : seedEmployees();
  } catch {
    // Хранилище недоступно — состояние живёт в памяти.
    memory ??= seedEmployees();
    return memory;
  }
}

export function writeEmployees(items: Employee[]): void {
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

/** Роли сотрудника с учётом выданного в Оргструктуре; нет записи — роли из `DEMO_USERS`. */
export function effectiveRoles(userId: string, fallback: readonly RoleCode[]): RoleCode[] {
  const employee = readEmployees().find((e) => e.id === userId);
  return employee ? [...employee.roles] : [...fallback];
}

/** Отключённый в Оргструктуре сотрудник входить не может (CRM отвечает как на неверный пароль). */
export function isEmployeeDisabled(userId: string): boolean {
  return readEmployees().find((e) => e.id === userId)?.status === "disabled";
}

export { accessFor };
