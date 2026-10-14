import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

/** Десктопная раскладка списков: media-запрос `(min-width: 1024px)` совпадает. */
function asDesktop() {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: query.includes('min-width: 1024px'),
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  return () => {
    window.matchMedia = original;
  };
}

describe('Сделка (deep-link бота)', () => {
  it('всё по сделке на одном экране', async () => {
    signedIn();
    renderApp('/deals/35');
    await heading('Сделка №35');
    for (const section of ['Запрос', 'Договор', 'Счета', 'Акты', 'Поставка', 'Документы']) {
      expect(await screen.findByRole('region', { name: section })).toBeInTheDocument();
    }
    expect(screen.queryByRole('region', { name: 'КП' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Счета' })).getByText('S-2026-0118')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Документы' })).getAllByRole('listitem')).toHaveLength(5);
    await expectNoAxeViolations();
  });

  it('чужая сделка — «не найдено»', async () => {
    signedIn();
    renderApp('/deals/999');
    expect(await screen.findByText('Такой страницы нет или она принадлежит другой компании.')).toBeInTheDocument();
  });
});

describe('Адаптивный список на десктопе', () => {
  let restore: () => void = () => undefined;
  beforeEach(() => {
    restore = asDesktop();
  });
  afterEach(() => restore());

  it('таблица с заголовками; строка открывается кликом и ссылкой с клавиатуры', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/quotes');
    const table = await screen.findByRole('table', { name: 'Коммерческие предложения' });
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'КП',
      'Статус',
      'Сумма',
      'Действует до',
      'Отправлено',
      'Сделка',
    ]);
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(6);

    // Клик по ячейке суммы — открывает КП; клик по ссылке «Сделка» — ведёт в сделку, а не в КП.
    await user.click(within(rows[1]).getByText('48 600 000 UZS'));
    expect(await heading('КП KP-2026-0042')).toBeInTheDocument();
    await router.navigate('/quotes');
    const again = await screen.findByRole('table', { name: 'Коммерческие предложения' });
    await user.click(within(again).getAllByRole('link', { name: 'Сделка №42' })[0]);
    expect(router.state.location.pathname).toBe('/deals/42');

    await router.navigate('/quotes');
    await screen.findByRole('table', { name: 'Коммерческие предложения' });
    // Фокус ставим, когда таблица устоялась (после возврата список может перерисоваться).
    await vi.waitFor(() => {
      const link = screen.getByRole('link', { name: 'KP-2026-0057 · версия 1' });
      link.focus();
      expect(link).toHaveFocus();
    });
    await user.keyboard('{Enter}');
    expect(await heading('КП KP-2026-0057')).toBeInTheDocument();
  });

  it('axe: таблицы счетов и строк КП', async () => {
    signedIn();
    const { router } = renderApp('/invoices');
    await screen.findByRole('table', { name: 'Счета' });
    await expectNoAxeViolations();
    router.navigate('/quotes/310');
    await screen.findByRole('table', { name: 'Состав предложения' });
    await expectNoAxeViolations();
  });
});
