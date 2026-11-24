import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';

import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations } from '@/test/screens';

/**
 * ДК-5 · запрос цены и заказ поставщику по личной ссылке партнёра: гость видит документ глазами партнёра — его позиции,
 * количество, его цены, срок, PDF; клиента заявки и нашей цены продажи на экране нет. Ответить на запрос и подтвердить заказ
 * можно только по коду: цены и сроки по строкам, комментарий, дата; контакт без права действовать — кнопка неактивна.
 */
const RFQ = 'rfq-token-0123456789';
const ORDER = 'order-token-0123456789';
const open = (token: string) => renderApp(`/d/${token}`);
const heading = (name: string) => screen.findByRole('heading', { level: 1, name });

describe('запрос цены по ссылке', () => {
  it('гость видит позиции и одно действие — «Ответить на запрос»; клиента, цены продажи и КП-кнопок нет', async () => {
    open(RFQ);
    await heading('Запрос цены Рельс Р65 и ещё 1 позиция');

    expect(screen.getByText('Рельс Р65, ГОСТ Р 51685')).toBeInTheDocument();
    expect(screen.getByText('Накладка двухголовая')).toBeInTheDocument();
    expect(screen.getByText('Нужны сертификаты соответствия.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ответить на запрос' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Скачать PDF: запрос цены' })).toBeEnabled();
    for (const name of ['Принять предложение', 'Вернуть с замечаниями', 'Задать вопрос', 'Подтвердить заказ']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText(/с НДС/)).not.toBeInTheDocument();
    expect(screen.queryByText('Сумма')).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('ответ: код, цены и срок по строкам, комментарий — одно действие со всеми данными', async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    portalServer.use(
      http.post('*/doc-links/act', async ({ request }) => {
        sent.push(await request.clone().json());
        return undefined;
      }),
    );
    open(RFQ);
    await heading('Запрос цены Рельс Р65 и ещё 1 позиция');
    await user.click(screen.getByRole('button', { name: 'Ответить на запрос' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });

    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Ответить на запрос' }));
    expect(await within(dialog).findByText('Напишите комментарий к ответу.')).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Цена за единицу: Рельс Р65, ГОСТ Р 51685'), '2480000,50');
    await user.type(within(dialog).getByLabelText('Срок поставки, дней: Рельс Р65, ГОСТ Р 51685'), '14');
    await user.type(within(dialog).getByLabelText('Коммерческие условия и цены *'), 'Цена действует месяц');
    await user.click(within(dialog).getByRole('button', { name: 'Ответить на запрос' }));

    expect(await screen.findByText('Ответ отправлен. Спасибо!')).toBeInTheDocument();
    expect(sent).toEqual([
      {
        token: RFQ,
        action: 'answer',
        text: 'Цена действует месяц',
        currency: 'UZS',
        prices: [{ id: 11, unit_price: '2480000.50', lead_days: 14 }],
      },
    ]);
    expect(screen.queryByRole('button', { name: 'Ответить на запрос' })).not.toBeInTheDocument();
  });

  it('цена не число — диалог не уходит на сервер', async () => {
    const user = userEvent.setup();
    open(RFQ);
    await heading('Запрос цены Рельс Р65 и ещё 1 позиция');
    await user.click(screen.getByRole('button', { name: 'Ответить на запрос' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });
    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.type(within(dialog).getByLabelText('Цена за единицу: Накладка двухголовая'), 'abc');
    await user.type(within(dialog).getByLabelText('Коммерческие условия и цены *'), 'x');
    await user.click(within(dialog).getByRole('button', { name: 'Ответить на запрос' }));

    expect(await within(dialog).findByText(/Цена — положительное число/)).toBeInTheDocument();
  });

  it('ответ уже дан: показан ответ партнёра, кнопки нет', async () => {
    open('rfq-done-0123456789');
    await heading('Запрос цены Рельс Р65 и ещё 1 позиция');

    expect(await screen.findByText('Ответ отправлен. Спасибо!')).toBeInTheDocument();
    expect(screen.getByText('Цена действует до конца месяца.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ответить на запрос' })).not.toBeInTheDocument();
  });

  it('контакт без права действовать: кнопка неактивна, причина написана рядом', async () => {
    open('rfq-viewer-0123456789');
    await heading('Запрос цены Рельс Р65 и ещё 1 позиция');

    expect(screen.getByRole('button', { name: 'Ответить на запрос' })).toBeDisabled();
    expect(screen.getByText(/нет права принимать решения/)).toBeInTheDocument();
  });
});

describe('заказ поставщику по ссылке', () => {
  it('гость видит свои цены, сумму и дату; одно действие — «Подтвердить заказ»', async () => {
    open(ORDER);
    await heading('Заказ ЗП-2026-031');

    expect(screen.getByText('Дата поставки')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Подтвердить заказ' })).toBeEnabled();
    expect(screen.getByText('Отгрузка на склад в Ташкенте, сертификаты — с первой партией.')).toBeInTheDocument();
    expect(screen.queryByText(/с НДС/)).not.toBeInTheDocument();
    for (const name of ['Принять предложение', 'Ответить на запрос', 'Подписать договор']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    await expectNoAxeViolations();
  });

  it('подтвердить: код — вход, и подтверждение уходит само, одним запросом', async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void calls.push(new URL(request.url).pathname.split('/doc-links/')[1] ?? ''));
    open(ORDER);
    await heading('Заказ ЗП-2026-031');
    await user.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });

    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить заказ' }));

    expect(await screen.findByText('Вы подтвердили заказ.')).toBeInTheDocument();
    expect(calls.filter((path) => path === 'act')).toHaveLength(1);
  });

  it('вошедший контакт подтверждает после вопроса «Подтвердить заказ?», код не нужен', async () => {
    signedIn();
    const user = userEvent.setup();
    open(ORDER);
    await heading('Заказ ЗП-2026-031');
    await user.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердить заказ?' });
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить заказ' }));

    expect(await screen.findByText('Вы подтвердили заказ.')).toBeInTheDocument();
  });

  it('в заказе нет даты: партнёр называет её сам, и она уходит с подтверждением', async () => {
    const user = userEvent.setup();
    const sent: unknown[] = [];
    portalServer.use(
      http.post('*/doc-links/act', async ({ request }) => {
        sent.push(await request.clone().json());
        return undefined;
      }),
    );
    signedIn();
    open('order-nodate-0123456789');
    await heading('Заказ ЗП-2026-031');
    await user.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердить заказ?' });

    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await within(dialog).findByText('Укажите дату поставки.')).toBeInTheDocument();
    expect(sent).toEqual([]);

    await user.type(within(dialog).getByLabelText('Плановая дата поставки'), '15122026');
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText('Вы подтвердили заказ.')).toBeInTheDocument();
    expect(sent).toEqual([{ token: 'order-nodate-0123456789', action: 'confirm', expected_date: '2026-12-15' }]);
  });

  it('заказ отменён отправителем: действий нет', async () => {
    open('order-cancelled-0123456789');
    await heading('Заказ ЗП-2026-031');

    expect(screen.getByText('Заказ отменён отправителем.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подтвердить заказ' })).not.toBeInTheDocument();
  });
});
