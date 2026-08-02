import type { i18n as I18nType, TFunction } from 'i18next';

import { DEAL_STAGE_LABEL_KEY } from '@/lib/codes';

/**
 * Локализация уведомлений по машинному коду (L1, spec-bilingual-ru-en-2026-08-02).
 *
 * Зеркало `activityText.ts`: бэкенд пишет `event_code` + `event_params`, человеческий текст
 * собирается ЗДЕСЬ на языке зрителя. `title`/`message` остаются RU-fallback — их печатают
 * строки, записанные до L1, и админские broadcast'ы без кода.
 *
 * Отдельный приём для кодов, у которых параметр — тоже код (стадия сделки, статус отгрузки,
 * уровень KYC): такие значения переводятся своим же словарём SPA, а не приходят словом с
 * сервера. Иначе английское уведомление печатало бы русское название стадии.
 */
export interface NotificationLike {
  event_code?: string | null;
  event_params?: Record<string, unknown> | null;
  title: string;
  message?: string;
}

/**
 * Параметры-коды → i18n-ключ словаря, которым их печатает интерфейс.
 *
 * Стадия сделки берёт ГОТОВЫЙ маппинг `DEAL_STAGE_LABEL_KEY` (единственный источник кодов
 * стадий в SPA), а не строит ключ из кода: ключи стадий в локали — camelCase
 * (`dealStages.contractSigned`), и самодельный `dealStages.CONTRACT_SIGNED` печатал бы
 * сырой код — поймано глазами на EN-проходе 02-08.
 */
const CODE_PARAM_DICTIONARIES: Record<string, (code: string) => string> = {
  stage_code: (code) => DEAL_STAGE_LABEL_KEY[code] ?? '',
  status_code: (code) => `fulfillmentPage.status.${code}`,
  level_code: (code) => `kycLevels.${code}`,
};

/**
 * Значения кодов-параметров заменяются переведёнными словами; если словарь не знает код,
 * оставляем сам код — он информативнее пустоты и сразу виден как пробел в словаре.
 */
function localiseParams(t: TFunction, i18n: I18nType, params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };
  for (const [name, toKey] of Object.entries(CODE_PARAM_DICTIONARIES)) {
    const raw = out[name];
    if (typeof raw === 'string' && raw) {
      const key = toKey(raw);
      out[name] = key && i18n.exists(key) ? t(key) : raw;
    }
  }
  return out;
}

/**
 * Шаблон пригоден к отрисовке, если он не требует подстановок или параметры есть. Строка,
 * записанная до L1, кода не несёт вовсе — она уйдёт в fallback.
 */
function renderable(i18n: I18nType, key: string, params: Record<string, unknown>): boolean {
  if (Object.keys(params).length > 0) return true;
  const template = i18n.getResource(i18n.language, 'translation', key) as string | undefined;
  return typeof template === 'string' && !template.includes('{{');
}

export function notificationTitle(t: TFunction, i18n: I18nType, entry: NotificationLike): string {
  const code = entry.event_code;
  const params = localiseParams(t, i18n, { ...(entry.event_params ?? {}) });
  const key = `notification.${code}.title`;
  if (code && i18n.exists(key) && renderable(i18n, key, params)) {
    return t(key, params);
  }
  return entry.title;
}

export function notificationMessage(t: TFunction, i18n: I18nType, entry: NotificationLike): string {
  const code = entry.event_code;
  const params = localiseParams(t, i18n, { ...(entry.event_params ?? {}) });
  const key = `notification.${code}.message`;
  if (code && i18n.exists(key) && renderable(i18n, key, params)) {
    return t(key, params);
  }
  return entry.message ?? '';
}
