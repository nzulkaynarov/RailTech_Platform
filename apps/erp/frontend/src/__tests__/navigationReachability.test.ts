/**
 * Инвариант волны U1: **если интерфейс предлагает переход, цель обязана быть достижима тому,
 * кому предложение показано.**
 *
 * Аудит UI 2026-07-30 нашёл 13 нарушений этого правила: видимость объекта считал сервер, а
 * доступ к странице — статический список ролей в реестре. После M1-ERP-02 волны 3 сторон
 * «покупатель / продавец» нет, и гейт страниц отбрасывает только неизвестный хэш, — поэтому
 * тест держит то, что осталось существенным: каждая предлагаемая цель — известная странице SPA.
 *
 * Проверяются три семейства точек перехода разом:
 *   1. пункты меню — то, что реально построил `buildNavigation`;
 *   2. маршруты документов — весь выход `documentRoute`;
 *   3. маршрут «к сделкам» — `DEALS_LIST_ROUTE`, на который переведены воронка и уведомления.
 *
 * Судья — `evaluatePageGuard`, тот самый, что решает в рантайме.
 */

import { describe, it, expect } from 'vitest';

import { buildNavigation, TENANT_NAV, TENANT_BOTTOM_NAV } from '@/config/navigation';
import { evaluatePageGuard } from '@/routes/pageGuard';
import { documentRoute, DEALS_LIST_ROUTE, type DocumentKind } from '@/lib/documentRoute';
import type { Capabilities } from '@/store/userStore';

const t = (key: string) => key;

const ALL_PERMISSIONS = [
  'quote.build', 'quote.send', 'quote.view_cost_margin', 'quote.edit_pricing',
  'quote.review', 'quote.approve_final', 'quote.approve', 'catalog.manage',
  'settings.edit', 'team.manage', 'data.export',
];

const PERSONAS: { name: string; caps: Capabilities }[] = [
  { name: 'сотрудник со всеми правами', caps: { permissions: ALL_PERMISSIONS } },
  { name: 'сотрудник без прав роли (список прав ещё не пришёл)', caps: { permissions: [] } },
  { name: 'сотрудник каталога', caps: { permissions: ['catalog.manage'] } },
];

/** Идентификаторы всех листьев меню, построенного движком для этой роли. */
function menuTargets(caps: Capabilities): string[] {
  const items = [
    ...buildNavigation(TENANT_NAV, caps, 'dashboard', t),
    ...buildNavigation(TENANT_BOTTOM_NAV, caps, 'dashboard', t),
  ];
  return items.flatMap((item) => (item.children ? item.children.map((child) => child.id) : item.id ? [item.id] : []));
}

/** Хэш без параметров: гейт решает по типу страницы, а не по конкретной записи. */
const pageTypeOf = (route: string) => route.split('?')[0].split('/')[0];

const isReachable = (route: string) => evaluatePageGuard(pageTypeOf(route)).action === 'allow';

describe('каждый пункт меню ведёт на известную страницу', () => {
  for (const persona of PERSONAS) {
    it(persona.name, () => {
      expect(menuTargets(persona.caps).filter((target) => !isReachable(target))).toEqual([]);
    });
  }
});

describe('маршрут документа ведёт на известную страницу', () => {
  const KINDS: DocumentKind[] = [
    'quote', 'contract', 'invoice', 'act', 'payment', 'fulfillment', 'generated', 'receipt', 'delivery_note',
  ];

  it('со сделкой и без неё', () => {
    const routes = KINDS.flatMap((kind) => [
      documentRoute({ kind, id: 42, dealId: 7 }),
      documentRoute({ kind, id: 42 }),
    ]);
    expect(routes.filter((route) => !isReachable(route))).toEqual([]);
  });

  it('КП ведёт в билдер сделки, без сделки — в реестр КП', () => {
    expect(documentRoute({ kind: 'quote', dealId: 7 })).toBe('deal-quote/7');
    expect(documentRoute({ kind: 'quote' })).toBe('crm-quotes');
  });

  it('акт открывается точечно', () => {
    expect(documentRoute({ kind: 'act', id: 5 })).toBe('acts?open=5');
  });
});

describe('маршрут «к сделкам» — очередь сделок бэк-офиса', () => {
  it('известен SPA', () => {
    expect(DEALS_LIST_ROUTE).toBe('crm-deals');
    expect(isReachable(DEALS_LIST_ROUTE)).toBe(true);
  });
});

describe('устаревшие покупательские хэши отбрасываются гейтом', () => {
  it('«Мои заявки» и «Поставщики» больше не страницы ERP (ушли в Cabinet)', () => {
    for (const stale of ['my-requests', 'suppliers']) {
      expect(evaluatePageGuard(stale)).toEqual({ action: 'bounce', reason: 'unknown' });
    }
  });
});
