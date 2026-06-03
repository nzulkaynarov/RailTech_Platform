import { describe, it, expect } from 'vitest';
import { toDecimal, calculateLineTotal, sumMoney, lineTotal, calculateVAT } from '../decimal';

// Money math is the highest-risk frontend area (it must agree with the backend's
// DecimalField). These guard against the float-drift class of bugs that raw
// parseFloat/`*` introduced before everything was routed through decimal.js.

describe('toDecimal', () => {
  it('treats null/undefined/empty as zero', () => {
    expect(toDecimal(null).toNumber()).toBe(0);
    expect(toDecimal(undefined).toNumber()).toBe(0);
    expect(toDecimal('').toNumber()).toBe(0);
  });
  it('parses numeric strings exactly', () => {
    expect(toDecimal('12.50').toNumber()).toBe(12.5);
  });
  it('falls back to zero on garbage instead of throwing', () => {
    expect(toDecimal('not-a-number').toNumber()).toBe(0);
  });
});

describe('sumMoney', () => {
  it('avoids binary float drift (0.1 + 0.2 === 0.3)', () => {
    expect(sumMoney([0.1, 0.2])).toBe(0.3);
  });
  it('sums mixed string/number values', () => {
    expect(sumMoney(['10.10', '20.20', 5])).toBe(35.3);
  });
  it('ignores null/undefined entries', () => {
    expect(sumMoney([10, null, undefined, '5'])).toBe(15);
  });
});

describe('lineTotal', () => {
  it('computes price × quantity without drift (19.99 × 3 === 59.97)', () => {
    expect(lineTotal('19.99', 3)).toBe(59.97);
  });
});

describe('calculateLineTotal', () => {
  it('returns an exact decimal string', () => {
    expect(calculateLineTotal('10.5', 3)).toBe('31.5');
  });
});

describe('calculateVAT', () => {
  it('computes a percentage of the subtotal exactly', () => {
    expect(calculateVAT('100', '12')).toBe('12');
    expect(calculateVAT('1420.00', '12')).toBe('170.4');
  });
});
