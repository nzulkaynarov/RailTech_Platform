/**
 * Плановое обновление (DECISIONS 2026-11-23): логика баннера без React. Файл `/maintenance.json` (его пишет
 * `scripts/maintenance-notice.sh`, снимает выкладка) — `{"starts_at": ISO8601 с часовым поясом, "minutes": 3, "kind": "planned"|"urgent"}`.
 * Нет файла, `{}` и любой мусор — баннера нет. Тот же расчёт — в apps/platform/web (src/features/maintenance/maintenance.ts); правка в одном — правка в обоих.
 */

export type MaintenanceKind = 'planned' | 'urgent';

export interface MaintenanceNotice {
  /** Начало работ, мс от эпохи (UTC) */
  startsAt: number;
  /** Сколько минут работа может быть прервана */
  minutes: number;
  kind: MaintenanceKind;
}

/** За сколько до начала показывать предупреждение */
export const WARN_BEFORE_MS = 30 * 60_000;
/** Скрыть баннер можно на 10 минут… */
export const DISMISS_MS = 10 * 60_000;
/** …но в последние 5 минут он возвращается */
export const REAPPEAR_BEFORE_MS = 5 * 60_000;
/** Рабочее время компании — ташкентское */
export const COMPANY_TZ = 'Asia/Tashkent';

const DEFAULT_MINUTES = 3;
const MAX_MINUTES = 240;
// Часовой пояс обязателен: «19:15» без пояса браузер прочёл бы в своём поясе — у сотрудника в другом городе баннер соврал бы.
const ISO_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

/** Разбор тела ответа; всё, что не похоже на предупреждение, — `null`. */
export function parseNotice(raw: unknown): MaintenanceNotice | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const { starts_at: startsAt, minutes, kind } = raw as Record<string, unknown>;
  if (typeof startsAt !== 'string' || !ISO_WITH_ZONE.test(startsAt)) return null;
  const ms = Date.parse(startsAt);
  if (Number.isNaN(ms)) return null;
  const mins =
    typeof minutes === 'number' && Number.isFinite(minutes) && minutes >= 1
      ? Math.min(Math.round(minutes), MAX_MINUTES)
      : DEFAULT_MINUTES;
  return { startsAt: ms, minutes: mins, kind: kind === 'urgent' ? 'urgent' : 'planned' };
}

export type MaintenancePhase = 'soon' | 'running';

export interface MaintenanceView {
  phase: MaintenancePhase;
  kind: MaintenanceKind;
  /** Время начала «ЧЧ:ММ» по Ташкенту */
  time: string;
  /** Пределы «работа прервётся на A–B минуты» */
  from: number;
  to: number;
  /** Окно «soon» можно скрыть на DISMISS_MS */
  dismissible: boolean;
}

/** «19:15» по Ташкенту независимо от пояса браузера. */
export function companyTime(ms: number): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: COMPANY_TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(ms);
}

/**
 * Что показать в момент `now`. `dismissedUntil` — до какого момента сотрудник скрыл баннер (0 — не скрывал): скрытое
 * держится до этого времени, но не позже `starts_at − 5 минут`; в последние 5 минут и во время работ баннер виден всегда.
 */
export function maintenanceView(
  notice: MaintenanceNotice | null,
  now: number,
  dismissedUntil = 0,
): MaintenanceView | null {
  if (!notice) return null;
  const { startsAt, minutes, kind } = notice;
  const end = startsAt + minutes * 60_000;
  let phase: MaintenancePhase;
  if (now >= end || now < startsAt - WARN_BEFORE_MS) return null;
  if (now >= startsAt) phase = 'running';
  else {
    phase = 'soon';
    if (now < dismissedUntil && startsAt - now > REAPPEAR_BEFORE_MS) return null;
  }
  return {
    phase,
    kind,
    time: companyTime(startsAt),
    from: Math.max(1, minutes - 1),
    to: minutes,
    dismissible: phase === 'soon' && startsAt - now > REAPPEAR_BEFORE_MS,
  };
}
