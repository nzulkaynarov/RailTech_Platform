import { initialPath, routeForStartParam } from '@/telegram/start-param';

describe('start_param → маршрут', () => {
  it.each([
    ['deal_42', '/deals/42'],
    ['quote_301', '/quotes/301'],
    ['web', null],
    ['deal_', null],
    ['deal_42/../admin', null],
    ['invoice_5', null],
    [undefined, null],
  ])('%s → %s', (param, route) => {
    expect(routeForStartParam(param)).toBe(route);
  });
});

describe('начальный адрес Mini App', () => {
  it('корень с deep-link ведёт на цель, другие адреса не трогает', () => {
    expect(initialPath('/', 'deal_42')).toBe('/deals/42');
    expect(initialPath('/', 'web')).toBe('/');
    expect(initialPath('/profile', 'deal_42')).toBe('/profile');
  });
});
