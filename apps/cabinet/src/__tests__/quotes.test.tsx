import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MOCK_ACCEPT_CODE } from '@/mocks/fixtures';
import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading } from '@/test/screens';

describe('КП', () => {
  it('список: все версии, сумма, срок, «ждут решения»', async () => {
    signedIn();
    renderApp('/quotes');
    await heading('Коммерческие предложения');
    expect(await screen.findByText('2 КП ждут вашего решения')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Коммерческие предложения' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    const first = within(list).getAllByRole('listitem')[0];
    expect(within(first).getByRole('link', { name: 'KP-2026-0042 · версия 2' })).toHaveAttribute('href', '/quotes/301');
    expect(within(first).getByText('48 600 000 UZS')).toBeInTheDocument();
    expect(within(first).getByText('25 окт. 2026 г.')).toBeInTheDocument();
    expect(within(list).getAllByText('Срок истёк')).toHaveLength(1);
    await expectNoAxeViolations();
  });

  it('карточка: разделы, позиции, заметки, обещанные даты, итог', async () => {
    signedIn();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    const lines = screen.getByRole('list', { name: 'Состав предложения' });
    expect(within(lines).getByText('Товары')).toBeInTheDocument();
    expect(within(lines).getByText('Подшипник 6205-2RS')).toBeInTheDocument();
    expect(within(lines).getByText('200 шт')).toBeInTheDocument();
    expect(within(lines).getByText('165 000 UZS')).toBeInTheDocument();
    expect(within(lines).getByText('5 нояб. 2026 г.')).toBeInTheDocument();
    expect(within(lines).getByText('Доставка до склада клиента в Ташкенте включена')).toBeInTheDocument();
    expect(screen.getAllByText('48 600 000 UZS').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('button', { name: 'Скачать: KP-2026-0042' })).toBeInTheDocument();
  });

  it('этапы услуги: КП по этапам с копейками', async () => {
    signedIn();
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    expect(screen.getByText('Этап 1. Обследование площадки и проект')).toBeInTheDocument();
    expect(screen.getAllByText('Этап')).toHaveLength(3);
    expect(screen.getAllByText('18 750 000,50 UZS').length).toBeGreaterThanOrEqual(1);
  });

  it('принять: неверный код → 409 с понятным текстом; верный → «договор формируется»', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/quotes/301/accept');
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog', { name: 'Принять КП KP-2026-0042' });

    await user.type(within(dialog).getByLabelText('Код подтверждения'), '12');
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(within(dialog).getByText('Код — не короче 4 символов.')).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText('Код подтверждения'));
    await user.type(within(dialog).getByLabelText('Код подтверждения'), '0000');
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(await within(dialog).findByText(/Код подтверждения неверен/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Код подтверждения')).toHaveAttribute('aria-invalid', 'true');
    await expectNoAxeViolations();

    await user.clear(within(dialog).getByLabelText('Код подтверждения'));
    await user.type(within(dialog).getByLabelText('Код подтверждения'), ` ${MOCK_ACCEPT_CODE.slice(0, 2)} ${MOCK_ACCEPT_CODE.slice(2)} `);
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));

    expect(await screen.findByText('КП принято')).toBeInTheDocument();
    expect(body.current).toEqual({ code: MOCK_ACCEPT_CODE });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Принято')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
    // Договор ERP создал сам — панель берёт номер из списка договоров.
    expect(await screen.findByText(/Договор D-2026-0042 готов/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'К договорам' })).toHaveAttribute('href', '/contracts');
  });

  it('уже принято другим (409 QUOTE_FINALIZED) — сообщение в диалоге', async () => {
    signedIn();
    failWith('post', '/quotes/301/accept', 409, 'QUOTE_FINALIZED');
    const user = userEvent.setup();
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    await user.click(screen.getByRole('button', { name: 'Принять' }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Код подтверждения'), MOCK_ACCEPT_CODE);
    await user.click(within(dialog).getByRole('button', { name: 'Принять КП' }));
    expect(await within(dialog).findByText('КП уже принято или отклонено — обновите страницу.')).toBeInTheDocument();
  });

  it('отклонить: причина обязательна, уходит в ERP', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/quotes/310/reject');
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отклонить КП KP-2026-0057' });
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить КП' }));
    expect(within(dialog).getByText(/Укажите причину/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText('Причина'), 'Дорого');
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить КП' }));
    expect(await screen.findByText('КП отклонено')).toBeInTheDocument();
    expect(screen.getByText('Причина: Дорого')).toBeInTheDocument();
    expect(body.current).toEqual({ reason: 'Дорого' });
  });

  it('истёкшее КП — объяснение вместо кнопок', async () => {
    signedIn();
    renderApp('/quotes/330');
    await heading('КП KP-2026-0033');
    expect(screen.getByText('Срок действия КП истёк')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
  });

  it('can_act=false: принять и отклонить скрыты', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/quotes/301');
    await heading('КП KP-2026-0042');
    expect(screen.getByText('Ждёт решения')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Принять' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).not.toBeInTheDocument();
  });

  it('чужое КП (404) — «не найдено» без подробностей', async () => {
    signedIn();
    renderApp('/quotes/999');
    expect(await heading('Страница не найдена')).toBeInTheDocument();
  });

  it('пусто — пустое состояние', async () => {
    signedIn('actor', 'empty');
    renderApp('/quotes');
    expect(await screen.findByText('КП пока нет')).toBeInTheDocument();
  });

  it('axe: карточка КП', async () => {
    signedIn();
    renderApp('/quotes/310');
    await heading('КП KP-2026-0057');
    await expectNoAxeViolations();
  });
});
