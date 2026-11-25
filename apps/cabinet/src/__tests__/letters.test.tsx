import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

describe('Письма (ЛИД-8, ADR-0026)', () => {
  it('наши письма с файлом и квитанции о ваших; фильтр по направлению и поиск', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/letters');
    await heading('Письма');
    expect(await screen.findAllByText('OUT-031/26')).not.toHaveLength(0);
    expect(screen.getAllByText('Ответ: OUT-031/26').length).toBeGreaterThan(0);
    expect(screen.getAllByText('На ваше IN-104/26').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Получено').length).toBeGreaterThan(0);
    // Скачать можно только наше исходящее.
    expect(screen.getAllByRole('button', { name: /^Скачать/ })).toHaveLength(1);
    await expectNoAxeViolations();

    await user.click(screen.getByRole('button', { name: 'Ваши' }));
    expect(await screen.findAllByText('IN-117/26')).not.toHaveLength(0);
    expect(screen.queryByText('Ответ на письмо о графике поставки')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Все' }));
    await user.type(screen.getByRole('searchbox', { name: 'Поиск писем' }), 'сверки');
    expect(await screen.findAllByText('Запрос акта сверки за III квартал')).not.toHaveLength(0);
    expect(screen.queryByText('О переносе графика поставки')).not.toBeInTheDocument();
  });

  it('«Письма» — в блоке «Документы» меню у клиента и у партнёра', async () => {
    signedIn('actor', 'demo', {
      roles: ['partner'],
      modules: ['my_products', 'letters', 'messages', 'profile'],
    });
    renderApp('/letters');
    await heading('Письма');
    const nav = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    const block = within(nav).getByRole('group', { name: 'Документы' });
    expect(within(block).getByRole('link', { name: 'Письма' })).toHaveAttribute('href', '/letters');
  });

  it('пусто — понятное пустое состояние', async () => {
    signedIn('actor', 'empty');
    renderApp('/letters');
    expect(await screen.findByText('Писем пока нет')).toBeInTheDocument();
  });
});
