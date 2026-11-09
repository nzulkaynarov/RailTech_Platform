import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { portalServer } from '@/mocks/server';
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

  it('FX-7: без даты заказ не подтверждается, диалог объясняет почему', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByText('PO-2026-0041');
    await user.click(screen.getAllByRole('button', { name: 'Подтвердить' })[0]!);
    const dialog = await screen.findByRole('dialog');
    await user.clear(within(dialog).getByLabelText('Плановая дата поставки'));
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить' }));

    expect(await within(dialog).findByText('Укажите дату поставки.')).toBeInTheDocument();
    expect(await screen.findByText('PO-2026-0041')).toBeInTheDocument();
  });

  it('FX-7: другая дата при подтверждении не меняет срок и показывает запрос на перенос', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByText('PO-2026-0041');
    await user.click(screen.getAllByRole('button', { name: 'Подтвердить' })[0]!);
    const confirm = await screen.findByRole('dialog');
    const date = within(confirm).getByLabelText('Плановая дата поставки');
    await user.clear(date);
    await user.type(date, '30112026');
    await user.click(within(confirm).getByRole('button', { name: 'Подтвердить' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(await screen.findByRole('button', { name: 'PO-2026-0041' }));
    const card = await screen.findByRole('dialog');
    expect(await within(card).findByText(/Вы запросили перенос на 30 нояб\. 2026/)).toBeInTheDocument();
    expect(within(card).getByText('20 нояб. 2026 г.')).toBeInTheDocument();
  });

  it('FX-7: отгрузка доступна только у подтверждённого заказа', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    renderApp('/partner/orders');

    await screen.findByText('PO-2026-0041');
    expect(screen.getAllByRole('button', { name: 'Отгрузить (ASN)' })).toHaveLength(1);
  });

  it('FX-7: запрос на перенос у подтверждённого заказа', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders?orderId=8002');

    const card = await screen.findByRole('dialog');
    await within(card).findByText('Заказ PO-2026-0042');
    await user.click(within(card).getByRole('button', { name: 'Перенести срок' }));

    const dialog = await screen.findByRole('dialog', { name: 'Запрос на перенос срока' });
    await user.type(within(dialog).getByLabelText(/Новая дата поставки/), '10122026');
    await user.type(within(dialog).getByLabelText('Причина'), 'Задержка сырья');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить запрос' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(await screen.findByRole('button', { name: 'PO-2026-0042' }));
    expect(await within(await screen.findByRole('dialog')).findByText(/Вы запросили перенос на 10 дек\. 2026/)).toBeInTheDocument();
  });

  it('FX-7: карточка несуществующего заказа показывает ошибку, а не вечный скелетон', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    renderApp('/partner/orders?orderId=999999');

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Не удалось открыть')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('FX-7: карточка несуществующего запроса цен показывает ошибку', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    renderApp('/partner/orders?view=rfq&rfqId=999999');

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Не удалось открыть')).toBeInTheDocument();
  });

  it('FX-7: ответ с ценами показывает цену партнёра и больше не предлагает ответить', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders?view=rfq');

    await screen.findByText('Запрос цен на тормозные колодки и втулки (Q4)');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText(/Коммерческие условия и цены/), 'Колодки в наличии');
    await user.type(await within(dialog).findByLabelText('Втулка резиновая'), 'абв');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить ответ' }));
    expect(await within(dialog).findByText(/Цена — положительное число/)).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText('Втулка резиновая'));
    await user.type(within(dialog).getByLabelText('Втулка резиновая'), '1250,50');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить ответ' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(await screen.findByRole('button', { name: 'Запрос цен на тормозные колодки и втулки (Q4)' }));
    const card = await screen.findByRole('dialog');
    expect(await within(card).findByText(/1\s250,50/)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Ответить' })).not.toBeInTheDocument();
  });

  it('отображает складские приёмки и расхождения в карточке заказа (K3-supply-docs)', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });

    // Открываем детали заказа PO-2026-0042
    const orderBtn = await screen.findByRole('button', { name: 'PO-2026-0042' });
    await user.click(orderBtn);

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Заказ PO-2026-0042')).toBeInTheDocument();

    // Проверяем секцию складских приёмок
    expect(within(dialog).getByText('Складские приёмки')).toBeInTheDocument();
    expect(within(dialog).getByText(/Приёмка #8301/)).toBeInTheDocument();
    expect(within(dialog).getByText(/ТН-1002 от 05.11.2026/)).toBeInTheDocument();
    expect(within(dialog).getByText('Центральный склад Ташкент')).toBeInTheDocument();
    expect(within(dialog).getByText(/ЕАЭС RU С-RU\.АЯ46\.В\.00001\/26/)).toBeInTheDocument();

    // Проверяем отображение позиций
    expect(within(dialog).getAllByText('Подшипник 6205-2RS').length).toBeGreaterThan(0);
  });

  it('переключается на взаиморасчёты и оценку (K4-partner-finance) и отображает сводку и показатели', async () => {
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });

    // Переключаемся на вкладку «Оборот и оценка»
    await user.click(screen.getByRole('button', { name: /Оборот и оценка/ }));

    // Проверяем наличие карточек взаиморасчётов и оценки
    expect(await screen.findByText('Оборот по заказам')).toBeInTheDocument();
    expect(screen.getByText('Оценка эффективности поставщика')).toBeInTheDocument();
    expect(screen.getByText('Разбивка по заказам')).toBeInTheDocument();

    // Проверяем показатели scorecard
    expect(screen.getByText(/OTIF/)).toBeInTheDocument();
    expect(screen.getByText('96.5%')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
    expect(screen.getByText('95%')).toBeInTheDocument();

    // Проверяем таблицу детализации
    expect(screen.getByText('PO-2026-0041')).toBeInTheDocument();
    expect(screen.getByText('PO-2026-0042')).toBeInTheDocument();
  });

  it('нет данных — пишет «Нет данных», без процента и оценки (FX-8)', async () => {
    portalServer.use(
      http.get('*/partner/finance', () =>
        HttpResponse.json({
          balances: [],
          scorecard: {
            otif_rate: null,
            otif_orders_count: 0,
            rfq_response_rate: null,
            rfq_avg_response_hours: null,
            total_rfqs_count: 0,
            price_freshness_rate: null,
            active_offers_count: 0,
          },
          settlements: [],
          settlements_total: 0,
          page: 1,
          page_size: 20,
        }),
      ),
    );
    signedIn('actor', 'demo', PARTNER_ACCESS);
    const user = userEvent.setup();
    renderApp('/partner/orders');

    await screen.findByRole('heading', { level: 1, name: 'Заказы на поставку' });
    await user.click(screen.getByRole('button', { name: /Оборот и оценка/ }));

    expect(await screen.findAllByText('Нет данных')).toHaveLength(3);
    expect(screen.queryByText('Отлично')).not.toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });
});
