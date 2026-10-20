import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';

import { NAV_ITEMS } from '@/app/nav';
import i18n from '@/i18n';
import { renderApp, signedIn } from '@/test/render';

describe('оболочка кабинета', () => {
  it('корень ведёт в «Запросы»: заголовок, title, нижняя и боковая навигация', async () => {
    signedIn();
    const { router } = renderApp('/');

    expect(await screen.findByRole('heading', { level: 1, name: 'Запросы' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/requests');
    await waitFor(() => expect(document.title).toBe('Запросы · RailTech Cabinet'));

    const bottom = screen.getByRole('navigation', { name: 'Основные разделы' });
    for (const name of ['Запросы', 'КП', 'Каталог', 'Документы', 'Ещё']) {
      expect(within(bottom).getByText(name)).toBeInTheDocument();
    }
    const side = screen.getByRole('navigation', { name: 'Разделы кабинета' });
    expect(within(side).getAllByRole('link')).toHaveLength(NAV_ITEMS.length);
    expect(within(side).getByRole('link', { name: 'Запросы' })).toHaveAttribute('aria-current', 'page');
    // Веб: компания в шапке, ссылка на профиль с подписью.
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Профиль' })).toHaveAttribute('href', '/profile');
  });

  it('у каждого раздела есть подпись во всех трёх словарях', () => {
    for (const language of ['ru', 'uz', 'en']) {
      for (const item of NAV_ITEMS) {
        expect(i18n.exists(item.labelKey, { lng: language }), `${language}: ${item.labelKey}`).toBe(true);
      }
    }
  });

  it('«Ещё» открывает остальные разделы и переходит в выбранный', async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });

    await user.click(screen.getByRole('button', { name: 'Ещё' }));
    const sheet = await screen.findByRole('dialog', { name: 'Ещё разделы' });
    await user.click(within(sheet).getByRole('link', { name: 'Акты' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Акты' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/acts');
  });

  it('у каждого раздела есть экран с заголовком', async () => {
    signedIn();
    const { router } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const titles: Record<string, string> = {
      '/quotes': 'Коммерческие предложения',
      '/contracts': 'Договоры',
      '/invoices': 'Счета',
      '/acts': 'Акты',
      '/deliveries': 'Поставки',
      '/documents': 'Документы',
      '/catalog': 'Каталог',
      '/company': 'Компания',
      '/team': 'Команда',
      '/requests/new': 'Новый запрос',
      '/quotes/301': 'КП KP-2026-0042',
      '/catalog/1001': 'Подшипник 6205-2RS',
      '/deals/42': 'Сделка № D-42',
    };
    for (const [path, title] of Object.entries(titles)) {
      await router.navigate(path);
      expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    }
    await router.navigate('/no-such-page');
    expect(await screen.findByRole('heading', { level: 1, name: 'Страница не найдена' })).toBeInTheDocument();
  });

  it('axe: оболочка без нарушений', async () => {
    signedIn();
    const { container } = renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
