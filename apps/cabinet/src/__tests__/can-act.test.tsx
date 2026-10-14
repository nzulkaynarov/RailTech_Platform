import { screen } from '@testing-library/react';

import { renderApp, signedIn } from '@/test/render';

describe('can_act', () => {
  it('с правом действовать — «Новый запрос» есть, плашки «только просмотр» нет', async () => {
    signedIn('actor');
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(screen.getByRole('link', { name: 'Новый запрос' })).toHaveAttribute('href', '/requests/new');
    expect(screen.queryByText(/Только просмотр/)).not.toBeInTheDocument();
  });

  it('без права (can_act=false) — действия скрыты, видна плашка «только просмотр»', async () => {
    signedIn('viewer');
    window.localStorage.setItem('cabinet.language', 'ru'); // явный выбор перекрывает язык контакта
    renderApp('/requests');
    await screen.findByRole('heading', { level: 1, name: 'Запросы' });
    expect(screen.queryByRole('link', { name: 'Новый запрос' })).not.toBeInTheDocument();
    const banner = await screen.findByText(/Только просмотр: действия доступны/);
    expect(banner.closest('[role="status"]')).not.toBeNull();
  });
});
