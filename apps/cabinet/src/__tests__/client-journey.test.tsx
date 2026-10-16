import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

describe('Путь клиента M2-CAB-04', () => {
  it('виджет «Требует вашего решения» на /requests отображает ожидающие документы', async () => {
    signedIn();
    renderApp('/requests');
    await heading('Запросы');

    const widget = await screen.findByRole('region', { name: 'Требует вашего решения' });
    expect(widget).toBeInTheDocument();
    expect(within(widget).getAllByText('Счёт').length).toBeGreaterThan(0);
    expect(within(widget).getAllByText('Договор').length).toBeGreaterThan(0);
    expect(within(widget).getAllByText('Акт').length).toBeGreaterThan(0);

    const invoiceLink = within(widget).getByRole('link', { name: 'S-2026-0124' });
    expect(invoiceLink).toHaveAttribute('href', '/invoices');

    const contractLink = within(widget).getByRole('link', { name: 'D-2026-0048' });
    expect(contractLink).toHaveAttribute('href', '/contracts');

    const actLink = within(widget).getByRole('link', { name: 'A-2026-0090' });
    expect(actLink).toHaveAttribute('href', '/acts');

    await expectNoAxeViolations();
  });

  it('мультивыбор в каталоге: выбор товаров, плашка и переход в форму запроса', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/catalog');
    await heading('Каталог');

    const list = await screen.findByRole('list', { name: 'Позиции каталога' });
    const bearing = within(list).getByRole('link', { name: 'Подшипник 6205-2RS' }).closest('article') as HTMLElement;
    const addBearing = within(bearing).getByRole('button', { name: 'В запрос: Подшипник 6205-2RS' });

    await user.click(addBearing);
    expect(within(bearing).getByRole('button', { name: 'Убрать из запроса: Подшипник 6205-2RS' })).toBeInTheDocument();

    const bar = await screen.findByRole('region', { name: 'Выбрано: 1' });
    expect(within(bar).getByText('Выбрано: 1')).toBeInTheDocument();

    await user.click(within(bar).getByRole('button', { name: 'Оформить запрос (1)' }));
    await heading('Новый запрос');
    expect(router.state.location.pathname).toBe('/requests/new');
    expect(screen.getByLabelText('Строка 1')).toHaveValue('Подшипник 6205-2RS');
  });

  it('поставки: приёмка строки и замечание', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/deliveries');
    await heading('Поставки');

    const acceptBtn = await screen.findByRole('button', { name: 'Принять позицию Редуктор червячный NMRV 063' });
    await user.click(acceptBtn);
    expect(await screen.findByText('Позиция принята')).toBeInTheDocument();

    const disputeBtn = screen.getByRole('button', { name: 'Оставить замечание к позиции Редуктор червячный NMRV 063' });
    await user.click(disputeBtn);

    expect(await screen.findByRole('dialog', { name: 'Замечание по позиции «Редуктор червячный NMRV 063»' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Причина замечания'), 'Повреждена упаковка при транспортировке');
    await user.click(screen.getByRole('button', { name: 'Отправить замечание' }));

    expect(await screen.findByText('Замечание отправлено менеджеру')).toBeInTheDocument();
  });

  it('документы: поиск фильтрует список', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/documents');
    await heading('Документы');

    const searchInput = await screen.findByRole('searchbox', { name: 'Поиск документов' });
    await user.type(searchInput, 'D-2026-0048');

    const list = screen.getByRole('list', { name: 'Документы' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByText(/D-2026-0048/)).toBeInTheDocument();

    await user.clear(searchInput);
    await user.type(searchInput, 'несуществующий-файл');
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Показать все' }));
    expect(within(screen.getByRole('list', { name: 'Документы' })).getAllByRole('listitem')).toHaveLength(9);
  });
});
