import { describe, it, expect } from 'vitest';
import { parseHashToPage, pageToHash, type Page } from '../routes/hashRoute';
import { evaluatePageGuard } from '../routes/pageGuard';

// WP-4 — cold-load deep-link regression guard.
//
// Раньше гейт страниц проверял контекст «покупатель / продавец» и на холодной загрузке
// (до /me) отбрасывал валидный deep-link (#request-detail/{id}, #deal-quote/{id}) на
// #dashboard. В M1-ERP-02 волне 3 контекст удалён: гейт отбрасывает только неизвестный хэш,
// поэтому валидный deep-link открывается всегда — и до, и после загрузки /me.

describe('parseHashToPage', () => {
  it('parses a parameterised request-detail deep link', () => {
    expect(parseHashToPage('#request-detail/3')).toEqual({ type: 'request-detail', dealId: 3 });
  });

  it('parses a parameterised deal-quote deep link', () => {
    expect(parseHashToPage('#deal-quote/7')).toEqual({ type: 'deal-quote', dealId: 7 });
  });

  it('parses a product_detail deep link', () => {
    expect(parseHashToPage('#product_detail/ABC-1')).toEqual({ type: 'product_detail', productId: 'ABC-1' });
  });

  it('falls back to the deals list for a bare/invalid request-detail hash', () => {
    expect(parseHashToPage('#request-detail')).toEqual({ type: 'crm-deals' });
    expect(parseHashToPage('#request-detail/notanumber')).toEqual({ type: 'crm-deals' });
  });

  it('falls back to crm-deals for an invalid deal-quote id', () => {
    expect(parseHashToPage('#deal-quote/xyz')).toEqual({ type: 'crm-deals' });
  });

  it('treats empty / #dashboard as dashboard', () => {
    expect(parseHashToPage('')).toEqual({ type: 'dashboard' });
    expect(parseHashToPage('#dashboard')).toEqual({ type: 'dashboard' });
  });

  it('strips a query suffix from the hash', () => {
    expect(parseHashToPage('#crm-quotes?deal=123')).toEqual({ type: 'crm-quotes' });
  });
});

describe('evaluatePageGuard — deep links of the back office', () => {
  it('opens request-detail and deal-quote deep links', () => {
    expect(evaluatePageGuard('request-detail')).toEqual({ action: 'allow' });
    expect(evaluatePageGuard('deal-quote')).toEqual({ action: 'allow' });
  });

  it('has no company-verification or client/seller gate: documents open for every employee', () => {
    // Проверки клиентов в ERP нет (волна 1c), сторон нет (волна 3) — действия ограничивает право роли.
    expect(evaluatePageGuard('contracts')).toEqual({ action: 'allow' });
    expect(evaluatePageGuard('acts')).toEqual({ action: 'allow' });
  });

  it('bounces a stale operator-plane hash (admin-*) like any unknown page (M1-ERP-02)', () => {
    expect(evaluatePageGuard('admin-users')).toEqual({ action: 'bounce', reason: 'unknown' });
  });

  it('bounces a stale client hash (#my-requests) — the page moved to Cabinet (M1-ERP-02 wave 3)', () => {
    expect(evaluatePageGuard('my-requests')).toEqual({ action: 'bounce', reason: 'unknown' });
  });

  it('bounces an unknown/stale hash to the dashboard (invalid hash → dashboard)', () => {
    expect(evaluatePageGuard('totally-bogus-page')).toEqual({ action: 'bounce', reason: 'unknown' });
  });
});

// ── Круговой обход хэша: URL обязан описывать экран ───────────────────────────
//
// `pageToHash` подставлял идентификатор только для `product_detail`; `request-detail`
// и `deal-quote` уходили в историю голыми. Назад/вперёд это не ломало (страница едет
// в `history.state`), но обновление страницы, закладка или отправленная коллеге ссылка
// уводили с карточки сделки на список сделок. Прямые присвоения `window.location.hash`
// (очередь согласования, уведомления) номер всегда клали — расходился ровно
// путь через `navigateTo`, то есть кнопка «Назад» из билдера КП.
describe('pageToHash — точная обратная операция к parseHashToPage', () => {
  const roundTrip = (page: Page) => parseHashToPage(`#${pageToHash(page)}`);

  it('сохраняет dealId карточки сделки', () => {
    expect(roundTrip({ type: 'request-detail', dealId: 7 })).toEqual({ type: 'request-detail', dealId: 7 });
  });

  it('сохраняет dealId билдера КП', () => {
    expect(roundTrip({ type: 'deal-quote', dealId: 42 })).toEqual({ type: 'deal-quote', dealId: 42 });
  });

  it('сохраняет productId карточки товара', () => {
    expect(roundTrip({ type: 'product_detail', productId: 'abc-1' })).toEqual({
      type: 'product_detail',
      productId: 'abc-1',
    });
  });

  it('непараметризованные маршруты проходят без изменений', () => {
    for (const type of ['dashboard', 'crm-deals', 'contracts', 'invoices'] as const) {
      expect(roundTrip({ type })).toEqual({ type });
    }
  });
});

describe('parseHashToPage — голые параметризованные маршруты не рендерят сломанный экран', () => {
  it('#deal-quote без номера откатывается на список сделок', () => {
    // Раньше проваливалось в общий `return { type: path }` → билдер КП монтировался
    // с `dealId: undefined`. Ветка `request-detail` голую форму обрабатывала, эта — нет.
    expect(parseHashToPage('#deal-quote')).toEqual({ type: 'crm-deals' });
  });

  it('#request-detail без номера откатывается на список сделок', () => {
    expect(parseHashToPage('#request-detail')).toEqual({ type: 'crm-deals' });
  });

  it('нечисловой номер откатывается так же, как отсутствующий', () => {
    expect(parseHashToPage('#deal-quote/abc')).toEqual({ type: 'crm-deals' });
    expect(parseHashToPage('#request-detail/abc')).toEqual({ type: 'crm-deals' });
  });
});
