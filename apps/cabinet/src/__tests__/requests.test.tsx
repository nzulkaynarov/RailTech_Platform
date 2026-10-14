import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { captureBody, expectNoAxeViolations, failWith, heading } from '@/test/screens';

describe('Запросы', () => {
  it('список: номер, суть, статус, сделка; строка открывается с клавиатуры', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await heading('Запросы');
    const list = await screen.findByRole('list', { name: 'Запросы' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    expect(within(list).getByText('Новый')).toBeInTheDocument();
    expect(within(list).getAllByText('Есть КП')).toHaveLength(2);
    expect(within(list).getByText('Ещё без сделки')).toBeInTheDocument();

    const link = within(list).getByRole('link', { name: /Z-2026-0042/ });
    link.focus();
    await user.keyboard('{Enter}');
    expect(await heading('Запрос Z-2026-0042')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests/501');
  });

  it('карточка: что дальше и КП по запросу', async () => {
    signedIn();
    renderApp('/requests/501');
    await heading('Запрос Z-2026-0042');
    expect(screen.getByText('КП готово — откройте его ниже.')).toBeInTheDocument();
    expect(screen.getByText('Через менеджера')).toBeInTheDocument();
    const quotes = await screen.findByRole('link', { name: /KP-2026-0042 · версия 2/ });
    expect(quotes).toHaveAttribute('href', '/quotes/301');
    await expectNoAxeViolations();
  });

  it('чужой или несуществующий запрос — «не найдено»', async () => {
    signedIn();
    renderApp('/requests/9999');
    expect(await heading('Страница не найдена')).toBeInTheDocument();
  });

  it('«Новый запрос»: проверка формы, строки свободным текстом → POST /requests по контракту', async () => {
    signedIn();
    const user = userEvent.setup();
    const body = captureBody('/requests');
    const { router } = renderApp('/requests');
    await heading('Запросы');
    await user.click(screen.getByRole('link', { name: 'Новый запрос' }));
    await heading('Новый запрос');

    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(screen.getByText('Опишите, что нужно, — хотя бы одной фразой.')).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveAttribute('aria-invalid', 'true');

    await user.type(screen.getByLabelText('Что нужно'), 'Кабель для цеха');
    await user.type(screen.getByLabelText('Строка 1'), 'Кабель ВВГнг 3×2,5');
    await user.type(screen.getByLabelText('Количество'), 'много');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(screen.getByText(/Количество — положительное число/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText('Количество'));
    await user.type(screen.getByLabelText('Количество'), '2,5');
    await user.type(screen.getByLabelText('Единица'), 'км');
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }));
    await user.type(screen.getByLabelText('Строка 2'), 'Монтаж');
    await user.click(screen.getByRole('button', { name: 'Добавить строку' }));
    await user.click(screen.getByRole('button', { name: 'Удалить строку 3' }));
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(await heading('Запрос Z-2026-0106')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests/506');
    expect(body.current).toEqual({
      summary: 'Кабель для цеха',
      lines: [
        { text: 'Кабель ВВГнг 3×2,5', quantity: '2.5', unit: 'км' },
        { text: 'Монтаж', quantity: null, unit: null },
      ],
    });
    expect(await screen.findByText('Запрос Z-2026-0106 отправлен')).toBeInTheDocument();
  });

  it('ошибка ERP при отправке — текст по коду, форма не теряется', async () => {
    signedIn();
    failWith('post', '/requests', 422, 'VALIDATION_ERROR');
    const user = userEvent.setup();
    renderApp('/requests/new');
    await heading('Новый запрос');
    await user.type(screen.getByLabelText('Что нужно'), 'Нужно что-то');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText('Проверьте заполненные поля.')).toBeInTheDocument();
    expect(screen.getByLabelText('Что нужно')).toHaveValue('Нужно что-то');
  });

  it('can_act=false: «Новый запрос» скрыт, прямой адрес формы объясняет почему', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru');
    const { router } = renderApp('/requests');
    await heading('Запросы');
    await screen.findByRole('list', { name: 'Запросы' });
    expect(screen.queryByRole('link', { name: 'Новый запрос' })).not.toBeInTheDocument();
    await router.navigate('/requests/new');
    expect(await screen.findByText('Создавать запросы может контакт с правом подтверждать')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить запрос' })).not.toBeInTheDocument();
  });

  it('пустой список — пустое состояние', async () => {
    signedIn('actor', 'empty');
    renderApp('/requests');
    expect(await screen.findByText('Запросов пока нет')).toBeInTheDocument();
  });

  it('axe: список и форма', async () => {
    signedIn();
    const { router } = renderApp('/requests');
    await screen.findByRole('list', { name: 'Запросы' });
    await expectNoAxeViolations();
    await router.navigate('/requests/new');
    await heading('Новый запрос');
    await expectNoAxeViolations();
  });
});
