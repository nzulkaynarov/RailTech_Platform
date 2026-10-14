import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading } from '@/test/screens';

function card(listName: string, title: string) {
  const list = screen.getByRole('list', { name: listName });
  const item = within(list)
    .getAllByRole('listitem')
    .find((li) => within(li).queryByText(title));
  if (!item) throw new Error(`нет карточки ${title}`);
  return item;
}

describe('Договоры', () => {
  it('статусы подписи обеих сторон; «Подписать» с подтверждением', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/contracts');
    await heading('Договоры');
    expect(await screen.findByText('2 договора ждут вашей подписи')).toBeInTheDocument();

    const signed = card('Договоры', 'D-2026-0035');
    expect(within(signed).getByText('Подписан сторонами')).toBeInTheDocument();
    expect(within(signed).getByText('20 авг. 2026 г., 15:30')).toBeInTheDocument();
    expect(within(signed).queryByRole('button', { name: /Подписать/ })).not.toBeInTheDocument();

    const pending = card('Договоры', 'D-2026-0029');
    expect(within(pending).getByText('Ждёт вашей подписи')).toBeInTheDocument();
    expect(within(pending).getByText('Файл ещё не выпущен')).toBeInTheDocument();
    await user.click(within(pending).getByRole('button', { name: 'Подписать договор D-2026-0029' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подписать договор D-2026-0029' });
    expect(within(dialog).getByText(/подтверждаете согласие с условиями договора/)).toBeInTheDocument();
    await expectNoAxeViolations();
    await user.click(within(dialog).getByRole('button', { name: 'Подписать договор' }));

    expect(await screen.findByText('Договор D-2026-0029 подписан обеими сторонами.')).toBeInTheDocument();
    expect(within(card('Договоры', 'D-2026-0029')).getByText('Подписан сторонами')).toBeInTheDocument();
    expect(await screen.findByText('1 договор ждёт вашей подписи')).toBeInTheDocument();
  });

  it('409 — договор уже подписан: понятное сообщение', async () => {
    signedIn();
    failWith('post', '/contracts/402/sign', 409, 'CONTRACT_FINALIZED');
    const user = userEvent.setup();
    renderApp('/contracts');
    await heading('Договоры');
    await user.click(await screen.findByRole('button', { name: 'Подписать договор D-2026-0048' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Подписать договор' }));
    expect(await within(dialog).findByText('Договор уже подписан или отменён — обновите страницу.')).toBeInTheDocument();
  });

  it('can_act=false — подписать нельзя, скачать можно', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/contracts');
    await screen.findByRole('list', { name: 'Договоры' });
    expect(screen.queryByRole('button', { name: /Подписать/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Скачать: D-2026-0048' })).toBeInTheDocument();
  });

  it('пусто', async () => {
    signedIn('actor', 'empty');
    renderApp('/contracts');
    expect(await screen.findByText('Договоров пока нет')).toBeInTheDocument();
  });
});

describe('Счета', () => {
  it('сумма, оплачено, остаток, срок; просрочка вычислена из due_date', async () => {
    signedIn();
    renderApp('/invoices');
    await heading('Счета');
    await screen.findByRole('list', { name: 'Счета' });

    const overdue = card('Счета', 'S-2026-0124');
    // Статус ERP — issued, но срок 7 октября прошёл: клиент видит «Просрочен».
    expect(within(overdue).getByText('Просрочен')).toBeInTheDocument();
    expect(within(overdue).getByText('просрочен на 7 дней')).toBeInTheDocument();

    const partial = card('Счета', 'S-2026-0118');
    expect(within(partial).getByText('Оплачен частично')).toBeInTheDocument();
    expect(within(partial).getByText('27 500 000 UZS')).toBeInTheDocument();
    expect(within(partial).getAllByText('13 750 000 UZS')).toHaveLength(2);
    expect(within(partial).getByRole('button', { name: 'Скачать: S-2026-0118' })).toBeInTheDocument();

    expect(screen.getByText('1 счёт просрочен')).toBeInTheDocument();
    // К оплате — по валютам, без смешивания сумов и долларов.
    expect(screen.getByText('23 550 000 UZS')).toBeInTheDocument();
    expect(screen.getByText('12 500 $', { selector: 'p' })).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('пусто', async () => {
    signedIn('actor', 'empty');
    renderApp('/invoices');
    expect(await screen.findByText('Счетов пока нет')).toBeInTheDocument();
  });
});

describe('Акты', () => {
  it('принять акт с подтверждением', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/acts');
    await heading('Акты');
    expect(await screen.findByText('1 акт ждёт вашей приёмки')).toBeInTheDocument();
    expect(within(card('Акты', 'A-2026-0084')).getByText('Возвращён: В акте не указан серийный номер редуктора')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Принять акт A-2026-0090' }));
    const dialog = await screen.findByRole('dialog', { name: 'Принять акт A-2026-0090' });
    await user.click(within(dialog).getByRole('button', { name: 'Принять акт' }));
    expect(await screen.findByText('Акт A-2026-0090 принят')).toBeInTheDocument();
    expect(within(card('Акты', 'A-2026-0090')).getByText('Принят')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Вернуть акт/ })).not.toBeInTheDocument();
  });

  it('вернуть акт: причина обязательна и уходит в ERP', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/acts/701/return');
    renderApp('/acts');
    await user.click(await screen.findByRole('button', { name: 'Вернуть акт A-2026-0090' }));
    const dialog = await screen.findByRole('dialog', { name: 'Вернуть акт A-2026-0090' });
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть акт' }));
    expect(within(dialog).getByText(/Укажите причину/)).toBeInTheDocument();
    await expectNoAxeViolations();
    await user.type(within(dialog).getByLabelText('Причина возврата'), 'Нет подписи');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть акт' }));
    expect(await screen.findByText('Акт A-2026-0090 возвращён исполнителю')).toBeInTheDocument();
    expect(within(card('Акты', 'A-2026-0090')).getByText('Возвращён: Нет подписи')).toBeInTheDocument();
    expect(body.current).toEqual({ reason: 'Нет подписи' });
  });

  it('409 — акт уже принят: понятное сообщение', async () => {
    signedIn();
    failWith('post', '/acts/701/accept', 409, 'ACT_FINALIZED');
    const user = userEvent.setup();
    renderApp('/acts');
    await user.click(await screen.findByRole('button', { name: 'Принять акт A-2026-0090' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Принять акт' }));
    expect(await within(dialog).findByText('Акт уже принят или возвращён — обновите страницу.')).toBeInTheDocument();
  });

  it('can_act=false — принять и вернуть скрыты; axe', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/acts');
    await screen.findByRole('list', { name: 'Акты' });
    expect(screen.queryByRole('button', { name: /Принять акт|Вернуть акт/ })).not.toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('пусто', async () => {
    signedIn('actor', 'empty');
    renderApp('/acts');
    expect(await screen.findByText('Актов пока нет')).toBeInTheDocument();
  });
});
