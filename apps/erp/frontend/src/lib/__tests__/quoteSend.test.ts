import { describe, it, expect } from 'vitest';
import type { Deal, Quote, QuoteApprovalStep } from '@/api/crmApi';
import { composeSendSummary, resolveDecision, publicQuoteUrl } from '@/lib/quoteSend';

/**
 * Wave B2 — the pure send-summary composition (Odoo composer). These pin the facts the
 * SendQuoteDialog renders and the QuoteSentPanel reuses: recipient · validity · margin-vs-floor ·
 * approval outcome, plus the post-send decision + public-URL derivation.
 */

const step = (over: Partial<QuoteApprovalStep>): QuoteApprovalStep => ({
  id: 1, order: 1, participation: 'APPROVER', status: 'APPROVED', approver: 2, approver_name: 'Olim',
  approver_role: null, acted_by: 2, acted_by_name: 'Olim', is_mandatory: true, is_auto: false,
  trigger_reason: '', comment: '', decided_at: null, created_at: '', can_act: false, ...over,
});

const makeQuote = (over: Partial<Quote>): Quote => ({
  id: 100, deal: 42, version: 1, status: 1, status_code: 'READY_TO_SEND', status_name: '',
  items: [], subtotal_excl_vat: '0', vat_amount: '0', total_incl_vat: '0', created_at: '', ...over,
} as Quote);

const makeDeal = (over: Partial<Deal>): Deal => ({ id: 42, created_at: '', ...over } as Deal);

describe('composeSendSummary — recipient', () => {
  it('prefers the client name, falls back to the company, else null (RECIPIENT_REQUIRED)', () => {
    expect(composeSendSummary(makeDeal({ client_name: 'ООО Клиент', company_name: 'X' }), makeQuote({})).recipient)
      .toBe('ООО Клиент');
    expect(composeSendSummary(makeDeal({ company_name: 'ООО Компания' }), makeQuote({})).recipient)
      .toBe('ООО Компания');
    expect(composeSendSummary(makeDeal({}), makeQuote({})).recipient).toBeNull();
  });
});

describe('composeSendSummary — validity', () => {
  it('passes through valid_until, or null when unset', () => {
    expect(composeSendSummary(makeDeal({}), makeQuote({ valid_until: '2026-08-01' })).validUntil).toBe('2026-08-01');
    expect(composeSendSummary(makeDeal({}), makeQuote({ valid_until: null })).validUntil).toBeNull();
  });
});

describe('composeSendSummary — margin vs floor', () => {
  it('marks ok / below from economics.below_floor and exposes the raw percents', () => {
    const ok = composeSendSummary(makeDeal({}), makeQuote({
      economics: { below_floor: false, gross_margin_percent: '18.00', min_margin_percent: '15.00' } as Quote['economics'],
    }));
    expect(ok.marginState).toBe('ok');
    expect(ok.marginPercent).toBe('18.00');
    expect(ok.floorPercent).toBe('15.00');

    const below = composeSendSummary(makeDeal({}), makeQuote({
      economics: { below_floor: true, gross_margin_percent: '4.20', min_margin_percent: '15.00' } as Quote['economics'],
    }));
    expect(below.marginState).toBe('below');
  });

  it('is hidden (no numbers) when the sender has no cost visibility (economics null)', () => {
    const summary = composeSendSummary(makeDeal({}), makeQuote({ economics: null }));
    expect(summary.marginState).toBe('hidden');
    expect(summary.marginPercent).toBeNull();
    expect(summary.floorPercent).toBeNull();
  });
});

describe('composeSendSummary — approval', () => {
  it('is auto when there is no chain or every step is auto (solo)', () => {
    expect(composeSendSummary(makeDeal({}), makeQuote({ approval_steps: [] })).approvalState).toBe('auto');
    expect(
      composeSendSummary(makeDeal({}), makeQuote({ approval_steps: [step({ is_auto: true, status: 'APPROVED' })] })).approvalState,
    ).toBe('auto');
  });

  it('is approved when a real chain is fully decided, and lists the approvers', () => {
    const summary = composeSendSummary(makeDeal({}), makeQuote({
      approval_steps: [
        step({ id: 1, participation: 'APPROVER', status: 'APPROVED', approver_name: 'Olim' }),
        step({ id: 2, participation: 'HEAD', status: 'APPROVED', approver_name: 'Dilnoza' }),
      ],
    }));
    expect(summary.approvalState).toBe('approved');
    expect(summary.approvers).toEqual(['Olim', 'Dilnoza']);
  });

  it('is pending while a real step is still awaiting a decision', () => {
    expect(
      composeSendSummary(makeDeal({}), makeQuote({ approval_steps: [step({ status: 'PENDING' })] })).approvalState,
    ).toBe('pending');
  });
});

describe('resolveDecision', () => {
  it('maps the КП status CODE to accepted / rejected / pending', () => {
    expect(resolveDecision('APPROVED')).toBe('accepted');
    expect(resolveDecision('REJECTED')).toBe('rejected');
    expect(resolveDecision('SENT')).toBe('pending');
  });
});

describe('publicQuoteUrl', () => {
  it('builds the no-login КП URL from the token, mirroring the backend pattern', () => {
    expect(publicQuoteUrl('abc123', 'https://erp.example.com'))
      .toBe('https://erp.example.com/api/v1/public/quotes/abc123/');
  });
  it('returns null when the token is absent (draft / not exposed yet)', () => {
    expect(publicQuoteUrl(null, 'https://x')).toBeNull();
    expect(publicQuoteUrl(undefined, 'https://x')).toBeNull();
  });
});
