import { describe, it, expect } from 'vitest';
import { translateApiError } from '../apiError';

// translateApiError turns backend UPPER_SNAKE codes into user-facing text. The
// invariant we lock down: a code that is NOT localised falls back to the raw
// code (never a blank/crash), and only valid-format codes are extracted. Using
// a deliberately-unlocalised code keeps these assertions locale-independent.
const UNLOCALISED = 'ZZ_NOT_A_REAL_CODE_123';

describe('translateApiError', () => {
  it('returns a plain string code unchanged when not localised', () => {
    expect(translateApiError(UNLOCALISED)).toBe(UNLOCALISED);
  });

  it('extracts the code from an axios error response.data.detail', () => {
    expect(translateApiError({ response: { data: { detail: UNLOCALISED } } })).toBe(UNLOCALISED);
  });

  it('extracts the code from response.data.error', () => {
    expect(translateApiError({ response: { data: { error: UNLOCALISED } } })).toBe(UNLOCALISED);
  });

  it('ignores non-code-shaped strings and yields a non-empty fallback', () => {
    const result = translateApiError({ response: { data: { detail: 'just a sentence' } } });
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
    expect(result).not.toBe('just a sentence');
  });

  it('never throws on unknown/null input', () => {
    expect(typeof translateApiError(null)).toBe('string');
    expect(typeof translateApiError(12345)).toBe('string');
    expect(typeof translateApiError(undefined)).toBe('string');
  });
});
