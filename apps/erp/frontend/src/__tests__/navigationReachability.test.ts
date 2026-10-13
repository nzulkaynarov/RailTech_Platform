/**
 * Инвариант волны U1: **если интерфейс предлагает переход, цель обязана быть достижима тому,
 * кому предложение показано.**
 *
 * Аудит UI 2026-07-30 нашёл 13 нарушений этого правила в пяти группах, и все они были одной
 * природы: видимость объекта считает сервер, а доступ к странице — статический список ролей в
 * реестре. Два источника правды разошлись, и каждое расхождение выглядело как отдельный «баг
 * с кнопкой». Заплатки по одной кнопке ловят следствие; тест ниже держит причину.
 *
 * Проверяются три семейства точек перехода разом:
 *   1. пункты меню — то, что реально построил `buildNavigation` для данной роли;
 *   2. маршруты документов — весь выход `documentRoute` для каждой стороны;
 *   3. маршрут «к сделке» — `dealsListRoute`, на который переведены чат, воронка и тур.
 *
 * Судья один и тот же — `evaluatePageGuard`, тот самый, что решает в рантайме. Проверять
 * принадлежность к наборам страниц напрямую было бы проверкой теста самим собой.
 */

import { describe, it, expect } from 'vitest';

import { buildNavigation, TENANT_NAV, type CapableSides } from '@/config/navigation';
import { evaluatePageGuard } from '@/routes/pageGuard';
import { documentRoute, dealsListRoute, type DocumentKind } from '@/lib/documentRoute';
import type { Capabilities, CompanyStatus, CompanyStatusEntry } from '@/store/userStore';

const t = (key: string) => key;

const ALL_PERMISSIONS = [
  'quote.build', 'quote.send', 'quote.view_cost_margin', 'quote.edit_pricing',
  'quote.review', 'quote.approve_final', 'quote.approve', 'catalog.manage',
  'settings.edit', 'team.manage', 'data.export',
];

interface Persona {
  name: string;
  caps: Capabilities;
  sides: CapableSides;
  kycStatus: string;
  activeStatus: CompanyStatus;
  statusEntries: CompanyStatusEntry[];
}

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    kyc_level: 'L2_VERIFIED',
    can_buy: true,
    can_sell: false,
    subscription_active: false,
    can_send_quotes: false,
    quote_send_is_demo: false,
    permissions: ALL_PERMISSIONS,
    ...overrides,
  };
}

const verified = (status: CompanyStatus): CompanyStatusEntry => ({ status, verification: 'verified' });

/** Роли, под которыми снята матрица доступа в аудите. */
const PERSONAS: Persona[] = [
  {
    name: 'покупатель (KYC пройден)',
    caps: capabilities(),
    sides: { buy: true, sell: false },
    kycStatus: 'verified',
    activeStatus: 'BUYER',
    statusEntries: [verified('BUYER')],
  },
  {
    name: 'продавец (KYC пройден, подписка активна)',
    caps: capabilities({ can_sell: true, can_buy: false, subscription_active: true, can_send_quotes: true }),
    sides: { buy: false, sell: true },
    kycStatus: 'verified',
    activeStatus: 'SELLER',
    statusEntries: [verified('SELLER')],
  },
  {
    name: 'компания с двумя сторонами',
    caps: capabilities({ can_sell: true, subscription_active: true, can_send_quotes: true }),
    sides: { buy: true, sell: true },
    kycStatus: 'verified',
    activeStatus: 'BUYER',
    statusEntries: [verified('BUYER'), verified('SELLER')],
  },
  {
    name: 'новичок до KYC',
    caps: capabilities({ kyc_level: 'L1_UNVERIFIED', permissions: [] }),
    sides: { buy: true, sell: false },
    kycStatus: 'not_started',
    activeStatus: 'BUYER',
    statusEntries: [],
  },
];

/** Идентификаторы всех листьев меню, построенного движком для этой роли. */
function menuTargets(persona: Persona): string[] {
  const items = buildNavigation(TENANT_NAV, persona.caps, persona.sides, 'dashboard', t);
  return items.flatMap((item) => (item.children ? item.children.map((child) => child.id) : item.id ? [item.id] : []));
}

/** Хэш без параметров: гейт решает по типу страницы, а не по конкретной записи. */
const pageTypeOf = (route: string) => route.split('?')[0].split('/')[0];

function guardFor(persona: Persona, route: string) {
  return evaluatePageGuard({
    pageType: pageTypeOf(route),
    kycStatus: persona.kycStatus,
    activeStatus: persona.activeStatus,
    statusEntries: persona.statusEntries,
    // Гейты применяем ПОСЛЕ бутстрапа: до него guard намеренно всё разрешает (холодный
    // deep-link), и тест на пред-авторизационных дефолтах ничего бы не доказывал.
    bootstrapped: true,
  });
}

describe('каждый пункт меню ведёт на страницу, доступную тому, кому он показан', () => {
  for (const persona of PERSONAS) {
    it(persona.name, () => {
      const unreachable = menuTargets(persona).filter((target) => guardFor(persona, target).action === 'bounce');
      expect(unreachable).toEqual([]);
    });
  }
});

describe('маршрут документа достижим стороне, которой документ показан', () => {
  const KINDS: DocumentKind[] = ['quote', 'contract', 'invoice', 'act', 'payment', 'fulfillment', 'generated'];

  for (const persona of PERSONAS.filter((p) => p.kycStatus === 'verified')) {
    it(persona.name, () => {
      const viewer = { isSeller: persona.sides.sell };
      const unreachable = KINDS
        .map((kind) => ({ kind, route: documentRoute({ kind, id: 42, dealId: 7 }, viewer) }))
        .filter((entry) => guardFor(persona, entry.route).action === 'bounce')
        .map((entry) => `${entry.kind} → ${entry.route}`);
      expect(unreachable).toEqual([]);
    });
  }

  it('покупателя ведут не в билдер КП, а на его вид того же документа', () => {
    // Билдер правит цены и себестоимость — это рабочее место продавца. Ссылка на КП у
    // покупателя обязана вести на карточку заявки, а не в отказ.
    expect(documentRoute({ kind: 'quote', dealId: 7 }, { isSeller: false })).toBe('request-detail/7');
    expect(documentRoute({ kind: 'quote', dealId: 7 }, { isSeller: true })).toBe('deal-quote/7');
  });

  it('акт ведёт на одну и ту же страницу обеим сторонам', () => {
    // Двусторонний документ (G2): выпускает исполнитель, принимает заказчик.
    expect(documentRoute({ kind: 'act', id: 5 }, { isSeller: false })).toBe('acts?open=5');
    expect(documentRoute({ kind: 'act', id: 5 }, { isSeller: true })).toBe('acts?open=5');
  });
});

describe('маршрут «к сделке» достижим той роли, которой его предлагают', () => {
  for (const persona of PERSONAS.filter((p) => p.kycStatus === 'verified')) {
    it(persona.name, () => {
      const route = dealsListRoute({ isSeller: persona.sides.sell });
      expect(guardFor(persona, route).action).not.toBe('bounce');
    });
  }

});
