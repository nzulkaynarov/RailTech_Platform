import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import * as fixtures from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';

import { dealProgress, type DealDocuments, type DealStageState } from '@/lib/dealStage';
import { renderApp, signedIn } from '@/test/render';
import { heading } from '@/test/screens';

/** Пустая сделка с одним запросом в работе; `docs(patch)` — нужные документы поверх. */
function docs(patch: Partial<DealDocuments> = {}): DealDocuments {
  return { requests: [{ status: 'in_progress' }], quotes: [], contracts: [], invoices: [], acts: [], deliveries: [], ...patch };
}

/** Состояния этапов строкой `id:state` — читаемее в сообщении об ошибке, чем массив объектов. */
function states(input: DealDocuments): string[] {
  return dealProgress(input).stages.map((stage) => `${stage.id}:${stage.state}`);
}

function stateOf(input: DealDocuments, id: string): DealStageState | undefined {
  return dealProgress(input).stages.find((stage) => stage.id === id)?.state;
}

describe('Этапы проекта по статусам документов (lib/dealStage, CAB-FIX-1)', () => {
  it('новый запрос без КП: запрос в работе, остальное впереди', () => {
    expect(states(docs({ requests: [{ status: 'new' }] }))).toEqual([
      'request:active',
      'quote:upcoming',
      'contract:upcoming',
      'payment:upcoming',
      'delivery:upcoming',
    ]);
  });

  it('запрос → КП: отправленное КП закрывает этап запроса, КП ждёт решения клиента', () => {
    const input = docs({ requests: [{ status: 'quoted' }], quotes: [{ status: 'sent' }] });
    expect(stateOf(input, 'request')).toBe('done');
    expect(stateOf(input, 'quote')).toBe('active');
  });

  it('отклонённое или просроченное КП — этап КП не выполнен', () => {
    expect(stateOf(docs({ quotes: [{ status: 'rejected' }] }), 'quote')).toBe('active');
    expect(stateOf(docs({ quotes: [{ status: 'expired' }] }), 'quote')).toBe('active');
  });

  it('КП принято → договор: этап КП выполнен, договор в работе, пока формируется', () => {
    const input = docs({ quotes: [{ status: 'rejected' }, { status: 'accepted' }] });
    expect(stateOf(input, 'quote')).toBe('done');
    expect(stateOf(input, 'contract')).toBe('active');
  });

  it('договор ждёт согласования клиента — не выполнен (случай D-48 из аудита)', () => {
    for (const status of ['sent', 'signed_by_company', 'signed_by_client'] as const) {
      expect(stateOf(docs({ quotes: [{ status: 'accepted' }], contracts: [{ status }] }), 'contract')).toBe('active');
    }
  });

  it('договор подписан сторонами → выполнен; отменённый договор не считается', () => {
    expect(stateOf(docs({ contracts: [{ status: 'signed' }] }), 'contract')).toBe('done');
    expect(stateOf(docs({ contracts: [{ status: 'cancelled' }] }), 'contract')).toBe('upcoming');
  });

  it('оплата: выполнена, только когда все выставленные счета оплачены', () => {
    expect(stateOf(docs({ invoices: [{ status: 'issued' }] }), 'payment')).toBe('active');
    expect(stateOf(docs({ invoices: [{ status: 'paid' }, { status: 'partially_paid' }] }), 'payment')).toBe('active');
    expect(stateOf(docs({ invoices: [{ status: 'paid' }, { status: 'overdue' }] }), 'payment')).toBe('active');
    expect(stateOf(docs({ invoices: [{ status: 'paid' }, { status: 'cancelled' }] }), 'payment')).toBe('done');
    expect(stateOf(docs({ invoices: [{ status: 'cancelled' }] }), 'payment')).toBe('upcoming');
  });

  it('поставка и акт: выполнены, когда все акты приняты и все строки доставлены или приняты', () => {
    expect(stateOf(docs({ deliveries: [{ status: 'in_transit' }] }), 'delivery')).toBe('active');
    expect(stateOf(docs({ acts: [{ status: 'issued' }], deliveries: [{ status: 'delivered' }] }), 'delivery')).toBe('active');
    expect(stateOf(docs({ acts: [{ status: 'returned' }] }), 'delivery')).toBe('active');
    expect(stateOf(docs({ acts: [{ status: 'accepted' }], deliveries: [{ status: 'disputed' }] }), 'delivery')).toBe('active');
    expect(
      stateOf(docs({ acts: [{ status: 'accepted' }], deliveries: [{ status: 'delivered' }, { status: 'accepted' }] }), 'delivery'),
    ).toBe('done');
    // Только поставка без акта — ещё не выполнено: акт и есть подтверждение.
    expect(stateOf(docs({ deliveries: [{ status: 'accepted' }] }), 'delivery')).toBe('active');
  });

  it('сделка целиком: каждый этап выполнен', () => {
    const input = docs({
      requests: [{ status: 'quoted' }],
      quotes: [{ status: 'accepted' }],
      contracts: [{ status: 'signed' }],
      invoices: [{ status: 'paid' }],
      acts: [{ status: 'accepted' }],
      deliveries: [{ status: 'accepted' }],
    });
    expect(dealProgress(input).stages.every((stage) => stage.state === 'done')).toBe(true);
  });

  it('без запроса в списке этап «Запрос» не показывается — меньше шагов вместо догадки', () => {
    expect(states(docs({ requests: [], quotes: [{ status: 'sent' }] }))[0]).toBe('quote:active');
  });

  it('закрытый запрос: только выполненные этапы, ни одного «в работе», флаг closed', () => {
    const lost = dealProgress(docs({ requests: [{ status: 'closed' }], quotes: [{ status: 'rejected' }] }));
    expect(lost.closed).toBe(true);
    expect(lost.stages).toEqual([{ id: 'request', state: 'done', current: false }]);

    const partly = dealProgress(
      docs({ requests: [{ status: 'closed' }], contracts: [{ status: 'signed' }], invoices: [{ status: 'partially_paid' }], acts: [{ status: 'issued' }] }),
    );
    expect(partly.stages.map((stage) => stage.id)).toEqual(['request', 'contract']);
    expect(partly.stages.some((stage) => stage.state !== 'done' || stage.current)).toBe(false);
  });

  it('текущий этап — ровно один, первый невыполненный; остальные начатые — просто «в работе» (CAB-FIX-3)', () => {
    const current = (input: DealDocuments) => dealProgress(input).stages.filter((stage) => stage.current).map((stage) => stage.id);
    // D-48: договор ждёт согласования, счёт на предоплату и поставка уже идут — текущий только договор
    const d48 = docs({
      requests: [{ status: 'quoted' }],
      quotes: [{ status: 'accepted' }],
      contracts: [{ status: 'sent' }],
      invoices: [{ status: 'issued' }],
      deliveries: [{ status: 'in_transit' }],
    });
    expect(current(d48)).toEqual(['contract']);
    expect(stateOf(d48, 'payment')).toBe('active');
    expect(current(docs({ requests: [{ status: 'new' }] }))).toEqual(['request']);
    // первый невыполненный — даже если он ещё не начат
    expect(current(docs({ requests: [], quotes: [] }))).toEqual(['quote']);
    // всё выполнено — текущего нет
    const finished = docs({
      requests: [{ status: 'quoted' }],
      quotes: [{ status: 'accepted' }],
      contracts: [{ status: 'signed' }],
      invoices: [{ status: 'paid' }],
      acts: [{ status: 'accepted' }],
      deliveries: [{ status: 'accepted' }],
    });
    expect(current(finished)).toEqual([]);
  });
});

describe('Этапы на странице проекта', () => {
  it('D-48: договор ждёт согласования — «Договор» текущий этап, оплата и поставка — «начато»', async () => {
    signedIn();
    renderApp('/deals/48');
    await heading('Проект D-48');
    const stages = await screen.findByRole('region', { name: 'Этапы проекта' });
    const items = within(stages).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Запрос, выполнено',
      'КП, выполнено',
      '3.Договор, текущий этап',
      '4.Оплата, начато',
      '5.Поставка и акт, начато',
    ]);
    expect(items.filter((item) => item.getAttribute('aria-current') === 'step')).toEqual([items[2]]);
    // «Что произойдёт» без действия на странице сделки нет.
    expect(screen.queryByText('Что произойдёт')).not.toBeInTheDocument();
  });

  it('D-35: закрытый запрос — «Запрос закрыт», без этапов «в работе» и без «исполнения»', async () => {
    signedIn();
    renderApp('/deals/35');
    await heading('Проект D-35');
    const stages = await screen.findByRole('region', { name: 'Этапы проекта' });
    expect(within(stages).getByText('Запрос закрыт')).toBeInTheDocument();
    expect(within(stages).queryByText(/текущий этап|начато/)).not.toBeInTheDocument();
    expect(within(stages).queryByText('Поставка и акт')).not.toBeInTheDocument();
  });

  it('КП с прошедшим сроком в списке проекта — «Срок истёк», а не «Ждёт решения»', async () => {
    signedIn();
    const lapsed = { ...fixtures.quotes[0], id: 399, ...fixtures.dealOf(48), number: 'KP-LAPSED', status: 'sent' as const, valid_until: '2026-10-01' };
    portalServer.use(http.get('*/api/portal/v1/quotes', () => HttpResponse.json([lapsed])));
    renderApp('/deals/48');
    await heading('Проект D-48');
    const quotes = await screen.findByRole('region', { name: 'КП' });
    expect(within(quotes).getByText('Срок истёк')).toBeInTheDocument();
    expect(within(quotes).queryByText(/Ждёт/)).not.toBeInTheDocument();
  });
});
