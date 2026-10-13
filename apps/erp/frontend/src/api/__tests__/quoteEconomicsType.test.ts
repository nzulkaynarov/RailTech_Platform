import { describe, it, expect } from 'vitest';
import type { QuoteEconomics } from '@/api/crmApi';
import type { components } from '@/api/schema';

/**
 * WP-G (K) — `QuoteEconomics` is now a re-export of the generated OpenAPI type
 * (`components['schemas']['QuoteEconomics']`), not a hand-written duplicate. This pins the swap:
 * the assignment below fails `tsc` if the two ever drift (missing/extra/renamed field), and the
 * runtime assertion keeps vitest counting the file.
 */
describe('QuoteEconomics generated-type re-export', () => {
  it('is structurally the generated schema type', () => {
    const generated: components['schemas']['QuoteEconomics'] = {
      total_landed_cost: '100',
      gross_profit: '20',
      gross_margin_percent: '16.7',
      markup_percent: '20',
      charge_cost_total: '0',
      operating_profit: '20',
      below_cost: false,
      below_floor: false,
      min_margin_percent: '10',
      target_margin_percent: '15',
      fx_missing: [],
    };
    // Cross-assign in BOTH directions — proves the alias and the generated type are identical.
    const econ: QuoteEconomics = generated;
    const roundTrip: components['schemas']['QuoteEconomics'] = econ;
    expect(roundTrip.below_cost).toBe(false);
    expect(roundTrip.fx_missing).toEqual([]);
  });
});
