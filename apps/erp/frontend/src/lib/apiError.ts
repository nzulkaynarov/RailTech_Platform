import i18n from '@/i18n';

/**
 * Translate backend error code into a localised user-facing string.
 *
 * Backend services return stable UPPER_SNAKE codes (see memory/tech_debt & CRITICAL-1 pass).
 * Frontend maps them via `apiErrors.<CODE>` i18n keys.
 *
 * ARCH-05: `{"detail": CODE}` is now the canonical API error shape (DRF-native) — every
 * hand-written backend error response uses it. The `.error` read below is a legacy
 * compatibility fallback only; do not add new backend responses that rely on it.
 *
 * Accepts:
 *  - plain string ("CONTRACT_NEEDS_APPROVAL")
 *  - Axios error (takes `error.response.data.detail`, with legacy `.error` fallback)
 *  - any unknown value (returns apiErrors.UNKNOWN)
 */
export function translateApiError(err: unknown): string {
  const code = extractCode(err);
  if (!code) return i18n.t('apiErrors.UNKNOWN');
  const key = `apiErrors.${code}`;
  const translated = i18n.t(key);
  if (translated !== key) return translated;
  // Перевода нет. Для кода БЭКЕНДА печатаем его как есть — это помогает и человеку («что-то
  // с ролью»), и разбору, пока новый код не локализован. А внутренний код транспорта axios
  // человеку не говорит ничего и вытесняет полезное сообщение — вместо него общий текст.
  if (isTransportCode(code)) return i18n.t('apiErrors.UNKNOWN');
  return code;
}

/**
 * Extract the stable UPPER_SNAKE backend error code from an unknown thrown value
 * (Axios error / plain string), or null. Exposed so callers can branch on a specific
 * code (e.g. re-prompt on BELOW_FLOOR_JUSTIFICATION_REQUIRED) without re-parsing Axios.
 */
export function extractApiErrorCode(err: unknown): string | null {
  return extractCode(err);
}

/**
 * Внутренние коды транспорта axios. Это НЕ коды бэкенда: они описывают, что случилось с
 * запросом, а не что ответил сервер.
 *
 * Прогон глазами 25-08: при недоступном списке компаний оператор видел красный тост
 * «ERR_NETWORK», а при отвергнутой загрузке файла — «ERR_BAD_REQUEST». `extractCode` брал
 * `err.code`, тот подходил под UPPER_SNAKE, перевода для него нет — и наружу уходил
 * внутренний код HTTP-клиента. Человеку он не говорит ничего, а полезное сообщение при этом
 * терялось.
 *
 * Часть из них имеет человеческий смысл (связи нет, сервер не ответил) — их переводим.
 * Остальные означают лишь «сервер ответил ошибкой, а кода в ответе не нашлось» — для них
 * общий текст честнее, чем внутренности клиента.
 */
const AXIOS_TRANSPORT_CODES = new Set([
  'ERR_NETWORK',
  'ECONNABORTED',
  'ETIMEDOUT',
  'ERR_CANCELED',
  'ERR_BAD_REQUEST',
  'ERR_BAD_RESPONSE',
  'ERR_FR_TOO_MANY_REDIRECTS',
  'ERR_BAD_OPTION',
  'ERR_BAD_OPTION_VALUE',
  'ERR_INVALID_URL',
  'ERR_DEPRECATED',
  'ERR_NOT_SUPPORT',
]);

export function isTransportCode(code: string): boolean {
  return AXIOS_TRANSPORT_CODES.has(code);
}

function extractCode(err: unknown): string | null {
  if (typeof err === 'string') return err;
  if (!err || typeof err !== 'object') return null;
  const anyErr = err as {
    response?: { data?: { detail?: unknown; error?: unknown; message?: unknown } };
    code?: unknown;
    message?: unknown;
  };
  const data = anyErr.response?.data;
  for (const candidate of [data?.detail, data?.error, data?.message, anyErr.code, anyErr.message]) {
    // Код может нести машинный суффикс после двоеточия («PRODUCT_INCOMPLETE:uom,category»,
    // как TEMPLATE_MISSING_REQUIRED_BLOCKS) — локализуется ГОЛОВА, суффикс отбрасывается.
    const match = typeof candidate === 'string' ? candidate.match(/^([A-Z][A-Z0-9_]+)(?::.*)?$/) : null;
    if (match) return match[1];
  }
  return null;
}
