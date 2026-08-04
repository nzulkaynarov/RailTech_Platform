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
  // If i18next returns the key itself — fall back to raw code (helps debugging
  // when a new backend code is not yet localised).
  if (translated === key) return code;
  return translated;
}

/**
 * Extract the stable UPPER_SNAKE backend error code from an unknown thrown value
 * (Axios error / plain string), or null. Exposed so callers can branch on a specific
 * code (e.g. re-prompt on BELOW_FLOOR_JUSTIFICATION_REQUIRED) without re-parsing Axios.
 */
export function extractApiErrorCode(err: unknown): string | null {
  return extractCode(err);
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
