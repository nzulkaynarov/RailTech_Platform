import type { QueueItem } from "../shared/api/generated/model";
import { readEmployees } from "./fixtures/employees";
import { allUsers, findUserById } from "./fixtures/users";

/**
 * Профиль сотрудника для MSW-моков (W15-H6): поля, фото, Telegram, замещение. Хранится в `localStorage` страницы по
 * сотруднику (как сессия и подписки мока); фото — сгенерированная заглушка/файл, выбранный в браузере, data-URL. Только для
 * моков и тестов.
 */
const KEY = "rt-pf-mock-profile";
/** Тест или e2e эмулирует «нажал Start в боте»: кладёт сюда ник — следующий опрос профиля увидит привязку. */
export const TELEGRAM_CONFIRM_KEY = "rt-pf-mock-tg-confirm";

export interface MockDeputy {
  id: string;
  date_from: string;
  date_to: string;
}

export interface MockProfile {
  name?: string;
  phone?: string;
  timezone: string;
  signature?: string;
  avatar?: string;
  avatarVersion?: number;
  telegramUsername?: string;
  pendingLink?: boolean;
  deputy?: MockDeputy;
}

const DEFAULTS: MockProfile = { timezone: "Asia/Tashkent" };
const memory = new Map<string, MockProfile>();

export function readProfile(userId: string): MockProfile {
  try {
    const raw = window.localStorage.getItem(`${KEY}-${userId}`);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as MockProfile) } : { ...DEFAULTS };
  } catch {
    // Хранилище недоступно — копия в памяти.
    return { ...DEFAULTS, ...memory.get(userId) };
  }
}

export function writeProfile(userId: string, value: MockProfile): void {
  memory.set(userId, value);
  try {
    window.localStorage.setItem(`${KEY}-${userId}`, JSON.stringify(value));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function patchProfile(userId: string, patch: Partial<MockProfile>): MockProfile {
  const next = { ...readProfile(userId), ...patch };
  writeProfile(userId, next);
  return next;
}

export function nameOf(userId: string): string {
  return readProfile(userId).name ?? findUserById(userId)?.name ?? "";
}

export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

export function avatarUrlOf(userId: string): string | undefined {
  const { avatar, avatarVersion } = readProfile(userId);
  return avatar && avatarVersion
    ? `/api/v1/staff/${userId}/avatar?v=${String(avatarVersion)}`
    : undefined;
}

/** Сегодня в формате `YYYY-MM-DD` (замещение считается по датам, не по моментам). */
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(now.getFullYear())}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export interface MockCovering {
  user_id: string;
  name: string;
  date_from: string;
  date_to: string;
}

/** За кого сотрудник замещает сегодня: чьё замещение назначено на него и период ещё идёт. */
export function coveringFor(userId: string, today = todayIso()): MockCovering[] {
  const active = new Set(
    readEmployees()
      .filter((e) => e.status !== "disabled")
      .map((e) => e.id),
  );
  return allUsers()
    .filter((u) => active.has(u.id) && u.id !== userId)
    .flatMap((u) => {
      const deputy = readProfile(u.id).deputy;
      return deputy?.id === userId && deputy.date_from <= today && today <= deputy.date_to
        ? [
            {
              user_id: u.id,
              name: nameOf(u.id),
              date_from: deputy.date_from,
              date_to: deputy.date_to,
            },
          ]
        : [];
    });
}

/** Строки очереди замещаемых коллег («за {имя}»): по одному ответу лиду на человека. */
export function coveredQueueItems(userId: string, roleId: string): QueueItem[] {
  return coveringFor(userId).map((c, index) => {
    const number = 9100 + index;
    return {
      id: `lead:${String(number)}:answer:for:${c.user_id}`,
      role_id: roleId,
      kind: "answer_lead",
      title: `Ответить лиду L-${String(number)}`,
      subtitle: "ООО «Демо-Мост» · уточняет сроки поставки · 2 ч назад",
      due_label: "today",
      object: {
        kind: "lead",
        number: `L-${String(number)}`,
        title: "ООО «Демо-Мост»",
        path: `/crm/messages?lead=${String(number)}`,
      },
      on_behalf_of: { id: c.user_id, name: c.name },
    };
  });
}
