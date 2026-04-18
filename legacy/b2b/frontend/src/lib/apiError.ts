import i18n from '@/i18n';

/**
 * Translate backend error code into a localised user-facing string.
 *
 * Backend services return stable UPPER_SNAKE codes (see memory/tech_debt & CRITICAL-1 pass).
 * Frontend maps them via `apiErrors.<CODE>` i18n keys.
 *
 * Accepts:
 *  - plain string ("CONTRACT_NEEDS_APPROVAL")
 *  - Axios error (takes `error.response.data.detail` or `.error`)
 *  - any unknown value (returns apiErrors.UNKNOWN)
 */
export function translateApiError(err: unknown): string {
  const code = extractCode(err);
  if (!code) return i18n.t('apiErrors.UNKNOWN');
  const key = `apiErrors.${code}`;
  const translated = i18n.t(key);
  // If i18next returns the key itself — fall back to raw code (helps debugging
  // when a new backend code is not yet localised).
  if (translated === key) return code;
  return translated;
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
    if (typeof candidate === 'string' && /^[A-Z][A-Z0-9_]+$/.test(candidate)) {
      return candidate;
    }
  }
  return null;
}
