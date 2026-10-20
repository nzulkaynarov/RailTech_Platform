import i18n from '@/i18n';
import { isPortalApiError } from './portal';

/**
 * Ошибка портала → ключ i18n (CLAUDE.md §5): код из `{"detail": CODE}`, для которого есть текст
 * `apiErrors.<CODE>`, показывается своим текстом; иначе — общий текст по HTTP-статусу.
 * 404 всегда «не найдено» — без намёка, существует ли чужая сущность.
 */
const BY_STATUS: Record<number, string> = {
  0: 'NETWORK',
  401: 'UNAUTHORIZED',
  403: 'FORBIDDEN',
  404: 'NOT_FOUND',
  410: 'MAGIC_LINK_EXPIRED',
  422: 'VALIDATION_ERROR',
};

export function apiErrorKey(error: unknown): string {
  if (!isPortalApiError(error)) return 'apiErrors.UNKNOWN';
  if (error.status === 404) return 'apiErrors.NOT_FOUND';
  const own = `apiErrors.${error.code}`;
  if (i18n.exists(own)) return own;
  const byStatus = BY_STATUS[error.status];
  return byStatus ? `apiErrors.${byStatus}` : 'apiErrors.UNKNOWN';
}

/**
 * Ошибка входа (magic-link, Telegram): 429 — лимит попыток входа (5 в час на адрес), 403 — доступ закрыт
 * (компания в архиве, Q-18); остальное — как везде.
 */
export function loginErrorKey(error: unknown): string {
  if (isPortalApiError(error, 429)) return 'auth.errors.TOO_MANY_REQUESTS';
  if (isPortalApiError(error, 403)) return 'auth.errors.FORBIDDEN';
  return apiErrorKey(error);
}
