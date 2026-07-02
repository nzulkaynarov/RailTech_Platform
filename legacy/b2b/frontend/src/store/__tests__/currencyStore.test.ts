import { describe, it, expect, beforeEach } from 'vitest';
import { useCurrencyStore } from '../currencyStore';

// Regression guard for the CRITICAL currency-display bug (F7): a UZS-priced КП was
// shown to the buyer as "$141,120,000" because format() assumed the input was USD.
// All app money is canonical UZS, so format(amountUZS) must render UZS as-is and only
// DIVIDE by the rate for a USD view — never prefix "$" on a raw UZS number, and never
// multiply a UZS number by the rate.
describe('currencyStore.format (UZS-canonical)', () => {
  beforeEach(() => {
    // Deterministic rate; reset to the UZS default before each case.
    useCurrencyStore.setState({ rate: 12650 });
    useCurrencyStore.getState().setCurrency('UZS');
  });

  it('defaults to UZS', () => {
    expect(useCurrencyStore.getState().currency).toBe('UZS');
  });

  it('does not rescale a UZS amount in UZS mode (the bug: never ×rate)', () => {
    // convert() is locale-free (returns a number) — the invariant that matters.
    expect(useCurrencyStore.getState().convert(141_120_000)).toBe(141_120_000);
    // The formatted string must NOT carry a "$" for a UZS amount.
    expect(useCurrencyStore.getState().format(141_120_000)).not.toContain('$');
  });

  it('converts UZS→USD in USD mode (the bug: never "$" on the raw UZS number)', () => {
    useCurrencyStore.getState().setCurrency('USD');
    // 141,120,000 UZS ÷ 12,650 ≈ 11,155.73 — a plausible USD amount, not 141M.
    const usd = useCurrencyStore.getState().convert(141_120_000);
    expect(usd).toBeGreaterThan(11_000);
    expect(usd).toBeLessThan(11_300);
    expect(useCurrencyStore.getState().format(141_120_000)).toContain('$');
  });

  it('rebuilds format identity on setCurrency so subscribers re-render (live toggle)', () => {
    const before = useCurrencyStore.getState().format;
    useCurrencyStore.getState().setCurrency('USD');
    const after = useCurrencyStore.getState().format;
    expect(after).not.toBe(before);
  });
});
