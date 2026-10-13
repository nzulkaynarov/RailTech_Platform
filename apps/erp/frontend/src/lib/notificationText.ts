import type { i18n as I18nType, TFunction } from 'i18next';

import { localizeParams, renderable } from './eventText';

/**
 * Локализация уведомлений по машинному коду (L1, spec-bilingual-ru-en-2026-08-02).
 *
 * Зеркало `activityText.ts`: бэкенд пишет `event_code` + `event_params`, человеческий текст
 * собирается ЗДЕСЬ на языке зрителя. `title`/`message` остаются RU-fallback — их печатают
 * строки, записанные до L1, и админские broadcast'ы без кода.
 *
 * Разрешение языка и подписи к кодовым параметрам (стадия сделки, статус отгрузки, уровень
 * KYC) — общие с журналом и живут в `eventText.ts`. Раньше это была вторая копия механики, и
 * починка регионального тега языка в журнале эту ленту не затронула (ux-review 03-08).
 */
export interface NotificationLike {
  event_code?: string | null;
  event_params?: Record<string, unknown> | null;
  title: string;
  message?: string;
}

export function notificationTitle(t: TFunction, i18n: I18nType, entry: NotificationLike): string {
  const code = entry.event_code;
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  const key = `notification.${code}.title`;
  if (code && i18n.exists(key) && renderable(i18n, key, params)) {
    return t(key, params);
  }
  return entry.title;
}

export function notificationMessage(t: TFunction, i18n: I18nType, entry: NotificationLike): string {
  const code = entry.event_code;
  const params = localizeParams(t, i18n, entry.event_params ?? {});
  const key = `notification.${code}.message`;
  if (code && i18n.exists(key) && renderable(i18n, key, params)) {
    return t(key, params);
  }
  return entry.message ?? '';
}
