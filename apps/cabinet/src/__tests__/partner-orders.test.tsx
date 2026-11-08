import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';

const PARTNER_ACCESS = {
  roles: ['partner' as const],
  modules: ['my_products', 'catalog_requests', 'messages', 'profile'],
};

describe('Заказы на поставку (PO, ASN) и запросы цен (RFQ) партнёра (K2-orders)', () => {
  it('отображает список заказов на поставку и позволяет подтвердить новый заказ', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    expect(await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' })).toBeInTheDocument();
    expect(await screen.findByText('PO-2026-0041')).toBeInTheDocument();
    expect(screen.getByText('PO-2026-0042')).toBeInTheDocument();

    // Нажимаем «Подтвердить» у заказа PO-2026-0041
    const confirmButtons = screen.getAllByRole('button', { name: 'Подтвердить' });
    await user.click(confirmButtons[0]!);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Подтверждение заказа на поставку')).toBeInTheDocument();

    const dateInput = within(dialog).getByLabelText('Плановая дата поставки');
    await user.clear(dateInput);
    await user.type(dateInput, '22112026');

    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('позволяет отправить уведомление об отгрузке (ASN) по заказу', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByText('PO-2026-0042');

    const shipButtons = screen.getAllByRole('button', { name: 'Отгрузить (ASN)' });
    await user.click(shipButtons[0]!);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Уведомление об отгрузке (ASN)')).toBeInTheDocument();

    const docInput = within(dialog).getByLabelText(/Номер накладной/);
    await user.type(docInput, 'УПД-550 от 08.11.2026');

    const carrierInput = within(dialog).getByLabelText(/Перевозчик/);
    await user.type(carrierInput, 'Автотранспорт');

    const trackingInput = within(dialog).getByLabelText(/Трек-номер/);
    await user.type(trackingInput, '01 A 777 AA');

    await user.click(within(dialog).getByRole('button', { name: 'Отгрузить (ASN)' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('переключается на запросы цен (RFQ) и отправляет коммерческий ответ', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });

    // Переключаемся на вкладку «Запросы цен (RFQ)»
    await user.click(screen.getByRole('button', { name: /Запросы цен \(RFQ\)/ }));

    expect(
      await screen.findByText('Запрос цен на тормозные колодки и втулки (Q4)'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Ответ на запрос цен (RFQ)')).toBeInTheDocument();

    const noteTextarea = within(dialog).getByLabelText(/Коммерческие условия и цены/);
    await user.type(noteTextarea, 'Колодки по 145 000 сум, в наличии на складе Ташкент.');

    await user.click(within(dialog).getByRole('button', { name: 'Отправить ответ' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    expect(await screen.findByText('Ответ дан')).toBeInTheDocument();
  });
});
