import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { renderApp, signedIn } from '../test/render';

const NEW_ACCOUNT = 'р/с 20208000555566667777, Банк «Пример»';

async function submitChange(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Изменить' }));
  const field = screen.getByLabelText('Банковские реквизиты');
  await user.clear(field);
  await user.type(field, NEW_ACCOUNT);
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
    expect(screen.getByText(/20208000900123456001/)).toBeInTheDocument();
    expect((await axe(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([]);
  });

  it('пока запрос на проверке, поле новой смены заблокировано', async () => {
    signedIn('actor');
    const user = userEvent.setup();
    renderApp('/company');

    await submitChange(user);
    await screen.findByRole('status', { name: /Запрос на смену банковских реквизитов/ });
    await user.click(await screen.findByRole('button', { name: 'Изменить' }));

    expect(screen.getByLabelText('Банковские реквизиты')).toBeDisabled();
    expect(screen.getByText(/Запрос уже на проверке/)).toBeInTheDocument();
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
