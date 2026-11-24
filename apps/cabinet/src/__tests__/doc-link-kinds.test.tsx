import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations } from '@/test/screens';

/**
 * ДК-3 · договор, счёт и акт по ссылке получателя: тот же гостевой вид и тот же диалог кода, что у КП, но свои факты и
 * свои действия — договор подписывают, акт принимают или возвращают, у счёта только реквизиты и справка «Оплатили?».
 * Ссылка одного вида не показывает кнопок другого и не принимает его действий.
 */
const CONTRACT = 'contract-token-0123456789';
const INVOICE = 'invoice-token-0123456789';
const PAID_INVOICE = 'invoice-paid-0123456789';
const ACT = 'act-token-0123456789';
const open = (token: string) => renderApp(`/d/${token}`);
const heading = (name: string) => screen.findByRole('heading', { level: 1, name });

describe('договор по ссылке', () => {
  it('гость видит договор и одно действие — «Подписать договор»; состава КП и чужих кнопок нет', async () => {
    open(CONTRACT);
    await heading('Договор CT-0042');

    expect(screen.getByRole('button', { name: 'Подписать договор' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Скачать PDF: договор CT-0042' })).toBeEnabled();
    for (const name of ['Принять предложение', 'Вернуть с замечаниями', 'Задать вопрос']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText('Состав предложения')).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('подписать: диалог кода, верный код — вход и подпись без второго нажатия', async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    portalServer.events.on('request:start', ({ request }) => void calls.push(new URL(request.url).pathname.split('/doc-links/')[1] ?? ''));
    open(CONTRACT);
    await heading('Договор CT-0042');

    await user.click(screen.getByRole('button', { name: 'Подписать договор' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });
    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Подписать договор' }));

    expect(await screen.findByText('Договор подписан вами. Дальше — счёт.')).toBeInTheDocument();
    expect(calls.filter((path) => path === 'act')).toHaveLength(1);
  });

  it('контакт без права действовать: кнопка неактивна, причина написана рядом', async () => {
    open('contract-viewer-0123456789');
    await heading('Договор CT-0042');

    expect(screen.getByRole('button', { name: 'Подписать договор' })).toBeDisabled();
    expect(screen.getByText(/нет права принимать решения/)).toBeInTheDocument();
  });
});

describe('счёт по ссылке', () => {
  it('реквизиты, срок и «Оплатили?»; ни одного действия над счётом', async () => {
    open(INVOICE);
    await heading('Счёт INV-0077');

    expect(screen.getByRole('heading', { level: 2, name: 'Реквизиты для оплаты' })).toBeInTheDocument();
    expect(screen.getByText(/Р\/с 2020 8000 1234 5678 9001/)).toBeInTheDocument();
    expect(screen.getByText(/Оплатили\? Платёж появится в счёте/)).toBeInTheDocument();
    expect(screen.getByText('Оплатить до')).toBeInTheDocument();
    for (const name of ['Принять предложение', 'Подписать договор', 'Принять акт', 'Вернуть с замечаниями', 'Задать вопрос']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Открыть Кабинет' })).toBeEnabled(); // вход в кабинет — тем же кодом
    await expectNoAxeViolations();
  });

  it('оплаченный счёт — «Счёт оплачен»', async () => {
    open(PAID_INVOICE);
    await heading('Счёт INV-0077');

    expect(await screen.findByText('Счёт оплачен.')).toBeInTheDocument();
  });
});

describe('акт по ссылке', () => {
  it('принять и вернуть; вопроса у акта нет', async () => {
    open(ACT);
    await heading('Акт ACT-0031');

    expect(screen.getByRole('button', { name: 'Принять акт' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Вернуть с замечаниями' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Задать вопрос' })).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('вернуть: без текста не уходит; с текстом и кодом — «возвращён с замечаниями»', async () => {
    const user = userEvent.setup();
    open(ACT);
    await heading('Акт ACT-0031');
    await user.click(screen.getByRole('button', { name: 'Вернуть с замечаниями' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите, что это вы' });

    await user.type(await within(dialog).findByLabelText('Код из письма'), '123456');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть с замечаниями' }));
    expect(await within(dialog).findByText(/Укажите причину/)).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Что нужно исправить?'), 'Неверная сумма');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть с замечаниями' }));

    expect(await screen.findByText('Акт возвращён с замечаниями.')).toBeInTheDocument();
  });

  it('вошедший контакт принимает акт после подтверждения, код не нужен', async () => {
    signedIn();
    const user = userEvent.setup();
    open(ACT);
    await heading('Акт ACT-0031');

    await user.click(screen.getByRole('button', { name: 'Принять акт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Принять акт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Принять акт' }));

    expect(await screen.findByText('Акт принят.')).toBeInTheDocument();
  });
});
