import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { portalServer } from '@/mocks/server';
import { renderApp } from '@/test/render';
import { expectNoAxeViolations } from '@/test/screens';

/**
 * ДВ-3: на экране входа — марка оператора (логотип своей компании, без него — буквы названия) и строка против фишинга.
 */
describe('бренд оператора на входе', () => {
  it('логотип из GET /operator; строка «мы не просим пароль и код»', async () => {
    portalServer.use(
      http.get('*/api/portal/v1/operator', () =>
        HttpResponse.json({ name: 'RailTech', bot_username: null, logo_url: '/media/companies/1/logo/demo.png' }),
      ),
    );
    renderApp('/login');

    const logo = await screen.findByRole('img', { hidden: true });
    expect(logo).toHaveAttribute('src', '/media/companies/1/logo/demo.png');
    expect(screen.getByText('Мы не просим пароль и код в письме или по телефону.')).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('без логотипа — буквы названия оператора', async () => {
    renderApp('/login');

    expect(await screen.findByText('RT')).toBeInTheDocument();
    expect(await screen.findByText('Кабинет RailTech')).toBeInTheDocument();
    expect(document.querySelector('img[src^="/media/"]')).toBeNull();
  });

  it('название приходит из данных запроса, а не из общей переменной i18n: шапка и заголовок вкладки', async () => {
    portalServer.use(
      http.get('*/api/portal/v1/operator', () =>
        HttpResponse.json({ name: 'Acme Trade', bot_username: null, logo_url: null }),
      ),
    );
    renderApp('/login');

    expect(await screen.findByText('Кабинет Acme Trade')).toBeInTheDocument();
    expect(screen.getByText('AT')).toBeInTheDocument();
    await vi.waitFor(() => expect(document.title).toBe('Вход в кабинет · Кабинет Acme Trade'));
  });

  it('название оператора не задано — нейтральный значок, а не буквы слова-заглушки («ПЛ»)', async () => {
    portalServer.use(
      http.get('*/api/portal/v1/operator', () =>
        HttpResponse.json({ name: null, bot_username: null, logo_url: null }),
      ),
    );
    renderApp('/login');

    expect(await screen.findByText('Вход в кабинет')).toBeInTheDocument();
    await vi.waitFor(() => expect(document.querySelector('header svg.lucide-layout-grid, svg.lucide-layout-grid')).not.toBeNull());
    expect(screen.queryByText('ПЛ')).not.toBeInTheDocument();
    expect(screen.queryByText('RT')).not.toBeInTheDocument();
  });
});
