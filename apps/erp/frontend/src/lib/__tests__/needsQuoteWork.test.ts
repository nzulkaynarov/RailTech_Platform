/**
 * Плитка «Заявки без КП» считает по СОСТОЯНИЮ КП, а не по факту его существования.
 *
 * Позиции заявки покупателя физически лежат в DRAFT-КП (`_request_draft_quote`: «The single
 * DRAFT quote holding the client's requested items»), поэтому признак `!active_quote` не бывает
 * истинным ни для одной ОТПРАВЛЕННОЙ заявки — плитка структурно показывала 0 всегда (проход
 * глазами 03-08), хотя комментарий рядом обещал «честный счёт».
 *
 * Эталон меряет состояние документа: Odoo Purchase — по `state`, Salesforce CPQ — «нет КП,
 * помеченного основным». Наше «продавец ещё не работал» = черновик без денег.
 */

import { describe, it, expect } from 'vitest';

import { needsQuoteWork } from '../waiting';

const draft = (total: string | number) => ({ status_code: 'DRAFT', total_incl_vat: total });

describe('«заявка ждёт КП»', () => {
  it('заявка с автосозданным пустым черновиком СЧИТАЕТСЯ ждущей', () => {
    // Ровно тот случай, что ломал плитку: КП есть, но это хранилище позиций покупателя.
    expect(needsQuoteWork({ stage_code: 'RFQ_OPEN', active_quote: draft('0.00') })).toBe(true);
  });

  it('заявка совсем без КП тоже ждёт', () => {
    expect(needsQuoteWork({ stage_code: 'RFQ_OPEN', active_quote: null })).toBe(true);
  });

  it('как только в КП появились деньги — заявка больше не ждёт', () => {
    expect(needsQuoteWork({ stage_code: 'CALCULATING', active_quote: draft('290518592.00') })).toBe(false);
  });

  it('КП вышло из черновика — заявка не ждёт, даже если сумма нулевая', () => {
    expect(
      needsQuoteWork({ stage_code: 'CALCULATING', active_quote: { status_code: 'SENT', total_incl_vat: '0.00' } }),
    ).toBe(false);
  });

  it('после отправки КП стадия уходит из пред-КП набора — заявка не ждёт', () => {
    expect(needsQuoteWork({ stage_code: 'QUOTE_SENT', active_quote: draft('0.00') })).toBe(false);
    expect(needsQuoteWork({ stage_code: 'CLOSED_WON', active_quote: null })).toBe(false);
  });

  it('черновик самого покупателя (стадия DRAFT) продавца не зовёт', () => {
    expect(needsQuoteWork({ stage_code: 'DRAFT', active_quote: draft('0.00') })).toBe(false);
  });
});
