import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { captureBody } from '@/test/screens';
import { renderApp, signedIn } from '../test/render';

const NEW_ACCOUNT = 'Расчётный счёт: 2020 8000 5555 6666 7777';

async function submitChange(user: ReturnType<typeof userEvent.setup>, account = '2020 8000 5555 6666 7777') {
  await user.click(await screen.findByRole('button', { name: 'Изменить' }));
  const field = screen.getByLabelText('Расчётный счёт');
  await user.clear(field);
  await user.type(field, account);
  await user.click(screen.getByRole('button', { name: 'Сохранить' }));
}

describe('FX-4: смена банковских реквизитов', () => {
  it('в форме сказано, что смена применяется только после проверки', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    renderApp('/company');

    await user.click(await screen.findByRole('button', { name: 'Изменить' }));

    expect(screen.getByText(/применятся только после проверки сотрудником/)).toBeInTheDocument();
  });

  it('после подачи — статус «на проверке», а действуют старые реквизиты', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    const { container } = renderApp('/company');

    await submitChange(user);

    const notice = await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    expect(within(notice).getByText(/На проверке/)).toBeInTheDocument();
    expect(within(notice).getByText(/Текущие реквизиты действуют/)).toBeInTheDocument();
    expect(within(notice).getByText(NEW_ACCOUNT)).toBeInTheDocument();
    expect(screen.getByText('2020 8000 9001 2345 6001')).toBeInTheDocument();
    expect((await axe(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([]);
  });

  it('пока запрос на проверке, поле новой смены заблокировано', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    renderApp('/company');

    await submitChange(user);
    await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    await user.click(await screen.findByRole('button', { name: 'Изменить' }));

    expect(screen.getByLabelText('Расчётный счёт')).toBeDisabled();
    expect(screen.getByText(/Запрос уже на проверке/)).toBeInTheDocument();
  });

  it('счёт уходит полями ISO 20022; неверный номер ловится до отправки', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    const body = captureBody('/company');
    renderApp('/company');

    await submitChange(user, '2020 8840 5555 6666 7777');
    expect(await screen.findByText(/Код валюты в номере/)).toBeInTheDocument();
    expect(body.current).toBeUndefined();

    const field = screen.getByLabelText('Расчётный счёт');
    await user.clear(field);
    await user.type(field, '2020 8000 5555 6666 7777');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    expect(body.current).toEqual({
      bank_account: {
        bank_country: 'UZ',
        currency: 'UZS',
        account: '20208000555566667777',
        mfo: '00440',
        bank_name: 'АКБ «Узпромстройбанк»',
      },
    });
  });

  it('счёт за рубежом: IBAN и SWIFT проверяются, страна банка — из SWIFT', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    const body = captureBody('/company');
    renderApp('/company');
    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    await user.click(screen.getByRole('button', { name: 'За рубежом' }));
    const iban = screen.getByLabelText('IBAN или номер счёта');
    await user.clear(iban);
    await user.type(iban, 'DE89 3704 0044 0532 0130 01');
    await user.type(screen.getByLabelText('SWIFT/BIC'), 'COBADEFF');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText(/IBAN не проходит проверку/)).toBeInTheDocument();

    await user.clear(iban);
    await user.type(iban, 'DE89 3704 0044 0532 0130 00');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    expect(body.current).toMatchObject({
      bank_account: { bank_country: 'DE', currency: 'UZS', account: 'DE89370400440532013000', swift: 'COBADEFF' },
    });
  });

  it('коллега без прав видит статус, но не новый счёт', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    const { unmount } = renderApp('/company');
    await submitChange(user);
    await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    unmount();

    signedIn('viewer');
    renderApp('/company');

    expect(await screen.findAllByRole('status', { name: /Запрос на смену банковских реквизитов|so.rovi/i })).toBeTruthy();
    expect(screen.queryByText(NEW_ACCOUNT)).not.toBeInTheDocument();
  });
});
