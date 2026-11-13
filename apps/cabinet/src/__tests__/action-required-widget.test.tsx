import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

/** Виджет «Требует вашего решения» на главной (`/requests`): C-4 аудита, FIX-24. */
describe('виджет «Требует вашего решения»', () => {
  async function widget() {
    signedIn();
    renderApp('/requests');
    await heading('Запросы');
    return screen.findByRole('region', { name: 'Требует вашего решения' });
  }

  it('КП и в статусе «отправлено», и «просмотрено»; принятые, отклонённые и просроченные не показываются', async () => {
    const region = await widget();
    expect(within(region).getByRole('link', { name: 'KP-2026-0042 · версия 2' })).toHaveAttribute('href', '/quotes/301'); // sent
    expect(within(region).getByRole('link', { name: 'KP-2026-0057 · версия 1' })).toHaveAttribute('href', '/quotes/310'); // viewed
    expect(within(region).queryByRole('link', { name: /KP-2026-0048/ })).not.toBeInTheDocument(); // принято
    expect(within(region).queryByRole('link', { name: /KP-2026-0033/ })).not.toBeInTheDocument(); // срок истёк
  });

  it('счета — только просроченные: срок прошёл и не оплачен; остальные неоплаченные не показываются', async () => {
    const region = await widget();
    expect(within(region).getByRole('link', { name: 'S-2026-0124' })).toHaveAttribute('href', '/invoices'); // due 2026-10-07
    expect(within(region).getByText('просрочен на 7 дней')).toBeInTheDocument();
    expect(within(region).queryByRole('link', { name: 'S-2026-0130' })).not.toBeInTheDocument(); // срок 28 окт
    expect(within(region).queryByRole('link', { name: 'S-2026-0118' })).not.toBeInTheDocument(); // частично оплачен, срок 30 окт
    expect(within(region).queryByRole('link', { name: 'S-2026-0101' })).not.toBeInTheDocument(); // оплачен
    await expectNoAxeViolations();
  });

  it('статус overdue от ERP показывается, даже если срок в данных ещё не прошёл', async () => {
    signedIn();
    portalServer.use(
      http.get('*/api/portal/v1/invoices', () =>
        HttpResponse.json([
          {
            id: 700,
            deal: { id: 29, number: 'ПР-2026-029', title: null },
            number: 'S-OVERDUE-1',
            status: 'overdue',
            total: { amount: '100.00', currency: 'UZS' },
            paid: { amount: '0.00', currency: 'UZS' },
            due_date: '2026-12-31',
            document_id: null,
          },
        ]),
      ),
    );
    renderApp('/requests');
    const region = await screen.findByRole('region', { name: 'Требует вашего решения' });
    expect(within(region).getByRole('link', { name: 'S-OVERDUE-1' })).toBeInTheDocument();
  });

  it('ошибка загрузки — видимое состояние ошибки с «Повторить», а не пустое место; повтор возвращает виджет', async () => {
    signedIn();
    const user = userEvent.setup();
    portalServer.use(http.get('*/api/portal/v1/invoices', () => HttpResponse.json({ detail: 'INTERNAL' }, { status: 500 }), { once: true }));
    renderApp('/requests');
    await heading('Запросы');
    const error = await screen.findByTestId('action-required-error');
    expect(within(error).getByText('Не удалось загрузить')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Требует вашего решения' })).not.toBeInTheDocument();
    await user.click(within(error).getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('region', { name: 'Требует вашего решения' })).toBeInTheDocument();
    expect(screen.queryByTestId('action-required-error')).not.toBeInTheDocument();
  });

  it('нечего решать — «все документы обработаны»', async () => {
    signedIn('actor', 'empty');
    renderApp('/requests');
    expect(await screen.findByText('Все документы обработаны — сейчас от вас ничего не требуется.')).toBeInTheDocument();
  });

  it('пока списки грузятся — скелетон на месте виджета, список запросов не показывается раньше виджета (K10)', async () => {
    signedIn();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    portalServer.use(
      http.get('*/api/portal/v1/acts', async () => {
        await gate;
        return HttpResponse.json([]);
      }),
    );
    renderApp('/requests');
    await heading('Запросы');
    expect(await screen.findByTestId('action-required-loading')).toBeInTheDocument();
    // запросы уже пришли, но список ждёт виджет: иначе виджет вставился бы над готовым списком
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole('table', { name: 'Запросы' })).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Запросы' })).not.toBeInTheDocument();
    release();
    expect(await screen.findByRole('region', { name: 'Требует вашего решения' })).toBeInTheDocument();
    expect(screen.queryByTestId('action-required-loading')).not.toBeInTheDocument();
    expect(await screen.findByText('ЗВ-2026-042')).toBeInTheDocument();
  });

  it('наблюдатель: «Ждут решения компании», без призыва к действию', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/requests');
    const region = await screen.findByRole('region', { name: 'Ждут решения компании' });
    expect(within(region).queryByText('Оплатить')).not.toBeInTheDocument();
    expect(within(region).queryByText('Посмотреть КП')).not.toBeInTheDocument();
    expect(within(region).getAllByText('Решает контакт с правом подтверждать').length).toBeGreaterThan(0);
    expect(screen.queryByRole('region', { name: 'Требует вашего решения' })).not.toBeInTheDocument();
  });

  it('суммы — по правилу Платформы: «сум», пробелы разрядов, без моноширинного шрифта', async () => {
    const region = await widget();
    const link = within(region).getByRole('link', { name: 'KP-2026-0042 · версия 2' });
    const card = link.closest('[data-slot="card"]') ?? link.parentElement?.parentElement;
    const amount = within(card as HTMLElement).getByText(/сум$/);
    expect(amount.textContent).toMatch(/^\d{1,3}(\u00a0\d{3})*(,\d{2})?\u00a0сум$/);
    expect(amount).toHaveClass('tabular-nums');
    expect(amount.className).not.toMatch(/font-mono/);
  });
});
