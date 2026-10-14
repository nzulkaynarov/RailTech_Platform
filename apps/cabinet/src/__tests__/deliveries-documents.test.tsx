import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { setDownloadWait } from '@/lib/download';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

afterEach(() => setDownloadWait(null));

describe('Поставки по строкам', () => {
  it('сгруппированы по сделке: статус, ожидаемая дата, трек', async () => {
    signedIn();
    renderApp('/deliveries');
    await heading('Поставки');
    const deal29 = await screen.findByRole('list', { name: 'Сделка №29' });
    expect(within(deal29).getAllByRole('listitem')).toHaveLength(3);
    expect(within(deal29).getByText('Комплектуем')).toBeInTheDocument();
    expect(within(deal29).getByText('Ожидается 24 окт. 2026 г.')).toBeInTheDocument();
    expect(within(deal29).getByText('Готово к отгрузке')).toBeInTheDocument();
    expect(within(deal29).getByText('UZP-77815230')).toBeInTheDocument();
    expect(within(deal29).getByText('Отгружено 12 окт. 2026 г., 11:00')).toBeInTheDocument();
    expect(screen.getByText('Доставлено 1 из 2')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Сделка №48' })).getByText('Дата уточняется')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Сделка №35' })).toHaveAttribute('href', '/deals/35');
    await expectNoAxeViolations();
  });

  it('пусто', async () => {
    signedIn('actor', 'empty');
    renderApp('/deliveries');
    expect(await screen.findByText('Поставок пока нет')).toBeInTheDocument();
  });
});

describe('Документы', () => {
  it('фильтр по виду — запрос kind к ERP и адрес страницы', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/documents');
    await heading('Документы');
    const list = await screen.findByRole('list', { name: 'Документы' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(9);

    await user.click(screen.getByRole('button', { name: 'Счета' }));
    expect(await screen.findByRole('button', { name: 'Счета', pressed: true })).toBeInTheDocument();
    expect(await screen.findByText('Счёт № S-2026-0118')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Документы' })).getAllByRole('listitem')).toHaveLength(1);
    await vi.waitFor(() => expect(router.state.location.search).toBe('?kind=invoice'));
    await expectNoAxeViolations();
  });

  it('скачать: 202 + Retry-After — «документ готовится», потом файл', async () => {
    signedIn();
    let release: () => void = () => undefined;
    setDownloadWait(() => new Promise<void>((resolve) => (release = resolve)));
    const user = userEvent.setup();
    renderApp('/documents');
    const button = await screen.findByRole('button', { name: 'Скачать: Договор поставки № D-2026-0048' });
    await user.click(button);
    expect(await within(button).findByText('Документ готовится…')).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
    release();
    await vi.waitFor(() => expect(window.URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(await within(button).findByText('Скачать')).toBeInTheDocument();
    vi.mocked(window.URL.createObjectURL).mockClear();
  });

  it('документ так и не готов — понятное сообщение, повторить позже', async () => {
    signedIn();
    setDownloadWait(() => Promise.resolve());
    const user = userEvent.setup();
    renderApp('/documents');
    await user.click(await screen.findByRole('button', { name: 'Скачать: Акт сверки за сентябрь 2026' }));
    expect(await screen.findByText('Документ ещё готовится. Попробуйте скачать через минуту.')).toBeInTheDocument();
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('пусто по виду и вообще', async () => {
    signedIn('actor', 'empty');
    renderApp('/documents?kind=waybill');
    expect(await screen.findByText('Документов этого вида нет')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Показать все' }));
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
  });
});
