/**
 * Каждое событие, которое пишет бэкенд, имеет подпись на обоих языках.
 *
 * Найдено ux-review 03-08: в АНГЛИЙСКОМ интерфейсе оператора лента активности была наполовину
 * русской. Одна из причин — у части кодов не было записи в словаре вовсе, и клиент падал на
 * текст, сохранённый в базу при записи (он всегда на русском).
 *
 * Список кодов НЕ переписывается руками: первая редакция этого теста перечисляла 26 кодов из
 * 65 существующих и пропустила ровно тот класс, ради которого писалась. Здесь коды читаются
 * из исходников бэкенда, а пространство имён определяется по тому, ЧТО пишет вызов: журнал
 * (`log_admin_action` / `ActivityLog`) печатается словарём `activity.*`, уведомление
 * (`notify_*` / `Notification`) — словарём `notification.*`. Одного «есть хоть где-нибудь»
 * мало: подпись в чужом пространстве имён не печатается.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, it, expect } from 'vitest';

import en from '../locales/en.json';
import ru from '../locales/ru.json';

const BACKEND = join(process.cwd(), '..', 'backend');
const SKIP_DIRS = new Set(['migrations', '__pycache__', 'tests', 'node_modules', '.venv']);

const WRITES_NOTIFICATION = /notify_|Notification\.objects\.create\(|Notification\(/;
const WRITES_ACTIVITY = /log_admin_action\(|ActivityLog\.objects\.create\(|ActivityLog\(|_log\(|_log_quote\(|_log_activity\(/;

function pythonFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (!SKIP_DIRS.has(name)) out.push(...pythonFiles(path));
    } else if (name.endsWith('.py') && !name.startsWith('test')) {
      out.push(path);
    }
  }
  return out;
}

/** `{ code → пространства имён, в которых он обязан иметь подпись }`. */
function collectEventCodes(): Map<string, Set<'activity' | 'notification'>> {
  const codes = new Map<string, Set<'activity' | 'notification'>>();
  for (const file of pythonFiles(BACKEND)) {
    const lines = readFileSync(file, 'utf-8').split('\n');
    lines.forEach((line, index) => {
      const match = /event_code="([a-z_.]+)"/.exec(line);
      if (!match) return;
      // Ближайший вверх по тексту вызов-производитель и решает, чья это лента.
      for (let cursor = index; cursor >= 0 && cursor > index - 45; cursor -= 1) {
        const kind = WRITES_NOTIFICATION.test(lines[cursor])
          ? ('notification' as const)
          : WRITES_ACTIVITY.test(lines[cursor])
            ? ('activity' as const)
            : null;
        if (!kind) continue;
        const known = codes.get(match[1]) ?? new Set<'activity' | 'notification'>();
        known.add(kind);
        codes.set(match[1], known);
        return;
      }
    });
  }
  return codes;
}

const EVENT_CODES = collectEventCodes();

function activityTitle(dict: unknown, code: string): string | undefined {
  const node = code
    .split('.')
    .reduce<unknown>(
      (branch, part) => (branch as Record<string, unknown>)?.[part],
      (dict as Record<string, unknown>).activity,
    );
  return (node as { title?: string } | undefined)?.title;
}

function notificationTitle(dict: unknown, code: string): string | undefined {
  const notifications = (dict as Record<string, Record<string, { title?: string }>>).notification;
  return notifications?.[code]?.title;
}

const titleOf = (dict: unknown, code: string, kind: 'activity' | 'notification') =>
  kind === 'activity' ? activityTitle(dict, code) : notificationTitle(dict, code);

/** Пары «код + чья лента» — по одной строке на каждое требование. */
const REQUIREMENTS = [...EVENT_CODES].flatMap(([code, kinds]) => [...kinds].map((kind) => ({ code, kind })));

describe('покрытие событий подписями', () => {
  it('коды прочитаны из бэкенда, а не выдуманы', () => {
    // Защита от молчаливого нуля: сломанный обход каталога сделал бы тест ниже пустым и зелёным.
    expect(REQUIREMENTS.length).toBeGreaterThan(50);
  });

  it.each(REQUIREMENTS)('$code имеет подпись в словаре $kind на обоих языках', ({ code, kind }) => {
    expect(titleOf(ru, code, kind), `нет ru-подписи ${kind}.${code}`).toBeTypeOf('string');
    expect(titleOf(en, code, kind), `нет en-подписи ${kind}.${code}`).toBeTypeOf('string');
  });

  it('английские подписи действительно английские, а не копия русских', () => {
    // Копия русского значения в en.json — та же проблема, только замаскированная.
    const cyrillic = REQUIREMENTS.filter(({ code, kind }) => /[А-Яа-я]/.test(titleOf(en, code, kind) ?? '')).map(
      ({ code }) => code,
    );

    expect(cyrillic).toEqual([]);
  });
});
