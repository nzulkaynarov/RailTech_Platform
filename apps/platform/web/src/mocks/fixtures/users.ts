import type { PresetCode } from "./roles";

/** Вымышленные сотрудники для MSW (репозиторий публичный: ни реальных имён, ни адресов). Домен `.example` зарезервирован. */
export interface DemoUser {
  id: string;
  email: string;
  name: string;
  initials: string;
  position: string;
  /** Роли при первом запуске — предустановки каталога (в моке их id 1–6) */
  roles: PresetCode[];
  language: "ru" | "uz" | "en";
  mustChangePassword?: boolean;
  /** Ошибка входа, которую отдаёт мок для этого адреса (проверка текстов экрана входа) */
  loginError?: { status: number; code: string; source: "bff" | "crm" };
}

export const DEMO_USERS: readonly DemoUser[] = [
  {
    id: "u-demo-manager",
    email: "manager@demo.example",
    name: "Демо Менеджеров",
    initials: "ДМ",
    position: "Менеджер по продажам",
    roles: ["MANAGER"],
    language: "ru",
  },
  {
    id: "u-demo-director",
    email: "director@demo.example",
    name: "Демо Директоров",
    initials: "ДД",
    position: "Директор",
    roles: ["DIRECTOR"],
    language: "ru",
  },
  {
    id: "u-demo-supply",
    email: "supply@demo.example",
    name: "Демо Снабженцев",
    initials: "ДС",
    position: "Специалист по снабжению",
    roles: ["SUPPLY"],
    language: "ru",
  },
  {
    id: "u-demo-engineer",
    email: "engineer@demo.example",
    name: "Демо Инженеров",
    initials: "ДИ",
    position: "Главный инженер",
    roles: ["ENGINEER"],
    language: "ru",
  },
  {
    id: "u-demo-accountant",
    email: "accountant@demo.example",
    name: "Демо Бухгалтеров",
    initials: "ДБ",
    position: "Бухгалтер",
    roles: ["ACCOUNTANT"],
    language: "ru",
  },
  {
    id: "u-demo-admin",
    email: "admin@demo.example",
    name: "Демо Админов",
    initials: "ДА",
    position: "Системный администратор",
    roles: ["ADMIN"],
    language: "ru",
  },
  {
    id: "u-demo-all",
    email: "all@demo.example",
    name: "Демо Универсалов",
    initials: "ДУ",
    position: "Исполняющий обязанности",
    roles: ["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN"],
    language: "ru",
  },
  {
    id: "u-demo-new",
    email: "new@demo.example",
    name: "Демо Новичков",
    initials: "ДН",
    position: "Менеджер по продажам",
    roles: ["MANAGER"],
    language: "ru",
    mustChangePassword: true,
  },
  {
    id: "u-demo-disabled",
    email: "disabled@demo.example",
    name: "Демо Отключённый",
    initials: "ДО",
    position: "—",
    roles: ["MANAGER"],
    language: "ru",
    loginError: { status: 401, code: "USER_DISABLED", source: "crm" },
  },
  {
    id: "u-demo-norole",
    email: "norole@demo.example",
    name: "Демо Безролев",
    initials: "ДБ",
    position: "—",
    roles: ["MANAGER"],
    language: "ru",
    loginError: { status: 403, code: "NO_PLATFORM_ROLE", source: "bff" },
  },
  {
    id: "u-demo-busy",
    email: "busy@demo.example",
    name: "Демо Занятой",
    initials: "ДЗ",
    position: "—",
    roles: ["MANAGER"],
    language: "ru",
    loginError: { status: 429, code: "TOO_MANY_REQUESTS", source: "bff" },
  },
  {
    id: "u-demo-down",
    email: "down@demo.example",
    name: "Демо Недоступный",
    initials: "ДН",
    position: "—",
    roles: ["MANAGER"],
    language: "ru",
    loginError: { status: 503, code: "BACKEND_UNAVAILABLE", source: "crm" },
  },
];

/** Пароль-образец: мок принимает любой непустой пароль, кроме этого (проверка `INVALID_CREDENTIALS`). */
export const DEMO_WRONG_PASSWORD = "wrong-password";
/** Текущий пароль, который мок смены пароля считает неверным (`WRONG_PASSWORD`). */
export const DEMO_WRONG_CURRENT_PASSWORD = "wrong-current";

/**
 * Сотрудники, созданные в моках на лету (первый администратор мастера «Первый запуск», W13-A4): хранятся в `localStorage`
 * рядом с сессией, без хранилища — в памяти. Демо-набор `DEMO_USERS` неизменен.
 */
const EXTRA_KEY = "rt-pf-mock-extra-users";
let extraMemory: DemoUser[] = [];

function readExtra(): DemoUser[] {
  try {
    const raw = window.localStorage.getItem(EXTRA_KEY);
    return raw ? (JSON.parse(raw) as DemoUser[]) : extraMemory;
  } catch {
    return extraMemory;
  }
}

export function registerUser(user: DemoUser): void {
  extraMemory = [...readExtra().filter((u) => u.id !== user.id), user];
  try {
    window.localStorage.setItem(EXTRA_KEY, JSON.stringify(extraMemory));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetExtraUsers(): void {
  extraMemory = [];
  temporaryPasswords.clear();
  try {
    window.localStorage.removeItem(EXTRA_KEY);
  } catch {
    // Нечего очищать.
  }
}

/** Меняет созданного на лету сотрудника (признак «пароль временный»); демо-набор неизменен. */
export function updateExtraUser(id: string, patch: Partial<DemoUser>): void {
  const current = readExtra();
  if (!current.some((u) => u.id === id)) return;
  extraMemory = current.map((u) => (u.id === id ? { ...u, ...patch } : u));
  try {
    window.localStorage.setItem(EXTRA_KEY, JSON.stringify(extraMemory));
  } catch {
    // Остаётся копия в памяти.
  }
}

/**
 * Выданные временные пароли (W13-A4): только в памяти страницы и только пока сотрудник не сменил пароль — вход мока
 * принимает для такого адреса именно этот пароль. Как в CRM, где пароль известен лишь тому, кому его показали.
 */
const temporaryPasswords = new Map<string, string>();

export function rememberTemporaryPassword(email: string, password: string): void {
  temporaryPasswords.set(email.trim().toLowerCase(), password);
}

export function temporaryPasswordOf(email: string): string | undefined {
  return temporaryPasswords.get(email.trim().toLowerCase());
}

export function forgetTemporaryPassword(email: string): void {
  temporaryPasswords.delete(email.trim().toLowerCase());
}

export function allUsers(): readonly DemoUser[] {
  return [...DEMO_USERS, ...readExtra()];
}

export function findUserById(id: string): DemoUser | undefined {
  return allUsers().find((u) => u.id === id);
}

export function findUser(email: string): DemoUser | undefined {
  return allUsers().find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
}
