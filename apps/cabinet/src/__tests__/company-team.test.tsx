import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading } from '@/test/screens';

describe('Компания', () => {
  it('профиль; правка отправляет только изменённые поля', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/company');
    renderApp('/company');
    await heading('Компания');
    expect(await screen.findByText('305123456')).toBeInTheDocument();
    expect(screen.getByText('Русский')).toBeInTheDocument();
    await expectNoAxeViolations();

    await user.click(screen.getByRole('button', { name: 'Изменить' }));
    const address = screen.getByLabelText('Юридический адрес');
    await user.clear(address);
    await user.type(address, 'г. Ташкент, ул. Новая, 1');
    await user.click(screen.getByRole('button', { name: 'Oʻzbekcha' }));
    await expectNoAxeViolations();
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText('Профиль компании сохранён')).toBeInTheDocument();
    expect(screen.getByText('г. Ташкент, ул. Новая, 1')).toBeInTheDocument();
    expect(body.current).toEqual({ legal_address: 'г. Ташкент, ул. Новая, 1', language: 'uz' });
  });

  it('пустое название не уходит; ошибка ERP (422) — текстом в форме', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/company');
    await user.click(await screen.findByRole('button', { name: 'Изменить' }));
    await user.clear(screen.getByLabelText('Название'));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByText('Укажите название компании.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Название'), 'ООО «Новое»');
    await user.clear(screen.getByLabelText('ИНН'));
    await user.type(screen.getByLabelText('ИНН'), '12');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('ИНН — от 9 до 14 цифр.')).toBeInTheDocument();
  });

  it('can_act=false — без «Изменить»', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/company');
    await screen.findByText('305123456');
    expect(screen.queryByRole('button', { name: 'Изменить' })).not.toBeInTheDocument();
  });
});

describe('Команда', () => {
  it('контакты компании: права, Telegram, последний вход; «Вы» и основной контакт', async () => {
    signedIn();
    renderApp('/team');
    await heading('Команда');
    const list = await screen.findByRole('list', { name: 'Команда' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    const me = within(list).getByRole('heading', { name: /Алишер Каримов/ }).closest('article') as HTMLElement;
    expect(within(me).getByText('Вы')).toBeInTheDocument();
    expect(within(me).getByText('Основной контакт')).toBeInTheDocument();
    expect(within(me).getByText('Может подтверждать')).toBeInTheDocument();
    const viewer = within(list).getByRole('heading', { name: /Dilnoza Yusupova/ }).closest('article') as HTMLElement;
    expect(within(viewer).getByText('Только просмотр')).toBeInTheDocument();
    expect(within(viewer).getByText('Не подключён')).toBeInTheDocument();
    expect(within(viewer).getByText(/Приглашён 2 окт. 2026 г., 11:30/)).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('«Пригласить коллегу»: проверка каналов и POST /team/invite по контракту', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/team/invite');
    renderApp('/team');
    await screen.findByRole('list', { name: 'Команда' });
    await user.click(screen.getByRole('button', { name: 'Пригласить коллегу' }));
    const dialog = await screen.findByRole('dialog', { name: 'Пригласить коллегу' });

    await user.click(within(dialog).getByRole('button', { name: 'Отправить приглашение' }));
    expect(within(dialog).getByText(/Укажите имя\. Укажите корректный e-mail\./)).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Имя и фамилия'), 'Бобур Алиев');
    await user.type(within(dialog).getByLabelText('E-mail'), 'b.aliev@toshlog.uz');
    await user.click(within(dialog).getByRole('checkbox', { name: 'В Telegram (по номеру телефона)' }));
    await user.click(within(dialog).getByRole('button', { name: 'Отправить приглашение' }));
    expect(within(dialog).getByText('Укажите телефон в международном формате.')).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('Телефон'), '+998901112233');
    await user.click(within(dialog).getByRole('checkbox', { name: 'Может подтверждать' }));
    await user.click(within(dialog).getByRole('button', { name: 'English' }));
    await expectNoAxeViolations();
    await user.click(within(dialog).getByRole('button', { name: 'Отправить приглашение' }));

    expect(await screen.findByText('Приглашение для Бобур Алиев отправлено')).toBeInTheDocument();
    expect(body.current).toEqual({
      name: 'Бобур Алиев',
      email: 'b.aliev@toshlog.uz',
      phone: '+998901112233',
      language: 'en',
      can_act: true,
      channels: ['email', 'telegram'],
    });
    expect(await screen.findByRole('heading', { name: 'Бобур Алиев' })).toBeInTheDocument();
  });

  it('ошибка ERP при приглашении — в диалоге', async () => {
    signedIn();
    failWith('post', '/team/invite', 403, 'FORBIDDEN');
    const user = userEvent.setup();
    renderApp('/team');
    await user.click(await screen.findByRole('button', { name: 'Пригласить коллегу' }));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByLabelText('Имя и фамилия'), 'Тест');
    await user.type(within(dialog).getByLabelText('E-mail'), 't@t.uz');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить приглашение' }));
    expect(await within(dialog).findByText('У вас нет права на это действие.')).toBeInTheDocument();
  });

  it('can_act=false — без «Пригласить коллегу»', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    renderApp('/team');
    await screen.findByRole('list', { name: 'Команда' });
    expect(screen.queryByRole('button', { name: 'Пригласить коллегу' })).not.toBeInTheDocument();
  });
});
