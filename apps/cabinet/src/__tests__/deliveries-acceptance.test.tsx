import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading, requestLog } from '@/test/screens';

const LINE = 'Редуктор червячный NMRV 063';

async function openDeliveries() {
  renderApp('/deliveries');
  await heading('Поставки');
  await screen.findByRole('list', { name: 'Сделка № D-35' });
}

describe('Приёмка поставки по строкам', () => {
  it('кнопки только у строки в статусе «Доставлено»; принятые и оспоренные показаны со статусом, датой и замечанием', async () => {
    signedIn();
    await openDeliveries();

    expect(screen.getAllByRole('button', { name: /^Принять позицию / })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: /^Оставить замечание к позиции / })).toHaveLength(1);
    expect(screen.getByRole('button', { name: `Принять позицию ${LINE}` })).toBeInTheDocument();

    const deal35 = screen.getByRole('list', { name: 'Сделка № D-35' });
    expect(within(deal35).getByText('Принято', { selector: 'span[data-slot="badge"], span' })).toBeInTheDocument();
    expect(within(deal35).getByText('Принято 27 сент. 2026 г., 10:15')).toBeInTheDocument();
    expect(within(deal35).getByText('Есть замечания', { selector: '[data-slot="badge"]' })).toBeInTheDocument();
    expect(within(deal35).getByText('Замечание: У двух канистр нарушена пломба')).toBeInTheDocument();
    expect(within(deal35).getByText('Замечание оставлено 27 сент. 2026 г., 10:20')).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('«Принять» → POST /deliveries/{id}/accept; тоста до запроса нет; строка становится «Принято»', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    await openDeliveries();
    expect(screen.queryByText(`Позиция «${LINE}» принята`)).not.toBeInTheDocument();
    expect(log.filter((entry) => entry.startsWith('POST'))).toEqual([]);

    await user.click(screen.getByRole('button', { name: `Принять позицию ${LINE}` }));

    expect(await screen.findByText(`Позиция «${LINE}» принята`)).toBeInTheDocument();
    expect(log).toContain('POST /deliveries/105/accept');
    const deal35 = screen.getByRole('list', { name: 'Сделка № D-35' });
    expect(await within(deal35).findByText('Принято 14 окт. 2026 г., 12:00')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: `Принять позицию ${LINE}` })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: `Оставить замечание к позиции ${LINE}` })).not.toBeInTheDocument();
  });

  it('«Есть замечания»: причина обязательна, уходит в POST /dispute {reason}; отмена не шлёт запрос', async () => {
    signedIn();
    const user = userEvent.setup();
    const log = requestLog();
    const body = captureBody('/deliveries/105/dispute');
    await openDeliveries();

    await user.click(screen.getByRole('button', { name: `Оставить замечание к позиции ${LINE}` }));
    const dialog = await screen.findByRole('dialog', { name: `Замечание по позиции «${LINE}»` });
    await user.click(within(dialog).getByRole('button', { name: 'Отправить замечание' }));
    expect(within(dialog).getByText(/Укажите причину/)).toBeInTheDocument();
    expect(log).not.toContain('POST /deliveries/105/dispute');

    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(log).not.toContain('POST /deliveries/105/dispute');
    expect(screen.queryByText('Замечание передано менеджеру')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: `Оставить замечание к позиции ${LINE}` }));
    const again = await screen.findByRole('dialog');
    await user.type(within(again).getByLabelText('Причина замечания'), 'Повреждена упаковка');
    await user.click(within(again).getByRole('button', { name: 'Отправить замечание' }));

    expect(await screen.findByText('Замечание передано менеджеру')).toBeInTheDocument();
    expect(body.current).toEqual({ reason: 'Повреждена упаковка' });
    const deal35 = screen.getByRole('list', { name: 'Сделка № D-35' });
    expect(await within(deal35).findByText('Замечание: Повреждена упаковка')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: `Принять позицию ${LINE}` })).not.toBeInTheDocument();
  });

  it.each([
    ['DELIVERY_LINE_NOT_ACCEPTABLE', 409, /уже нельзя принять или оспорить/],
    ['FORBIDDEN', 403, /нет права на это действие/],
    ['NOT_FOUND', 404, /Не найдено/],
    ['TOO_MANY_REQUESTS', 429, /Слишком много запросов/],
  ])('приёмка: %s (%i) — ошибка показана, строка не меняется', async (code, status, text) => {
    signedIn();
    failWith('post', '/deliveries/105/accept', status, code);
    const user = userEvent.setup();
    await openDeliveries();
    await user.click(screen.getByRole('button', { name: `Принять позицию ${LINE}` }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText(`Позиция «${LINE}» принята`)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: `Принять позицию ${LINE}` })).toBeEnabled();
  });

  it('замечание: ошибка ERP остаётся в диалоге', async () => {
    signedIn();
    failWith('post', '/deliveries/105/dispute', 409, 'DELIVERY_LINE_NOT_ACCEPTABLE');
    const user = userEvent.setup();
    await openDeliveries();
    await user.click(screen.getByRole('button', { name: `Оставить замечание к позиции ${LINE}` }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Причина замечания'), 'Брак');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить замечание' }));
    expect(await within(dialog).findByText(/уже нельзя принять или оспорить/)).toBeInTheDocument();
    expect(screen.queryByText('Замечание передано менеджеру')).not.toBeInTheDocument();
  });

  it('can_act=false: кнопок приёмки нет, статусы видны', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    const log = requestLog();
    await openDeliveries();
    expect(screen.queryByRole('button', { name: /^Принять позицию / })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Оставить замечание/ })).not.toBeInTheDocument();
    expect(screen.getByText('Доставлено')).toBeInTheDocument();
    expect(log.filter((entry) => entry.startsWith('POST'))).toEqual([]);
  });
});
