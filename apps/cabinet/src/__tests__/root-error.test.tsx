import { render, screen } from '@testing-library/react';
import { createMemoryRouter } from 'react-router-dom';

import { App } from '@/app/App';
import { createQueryClient } from '@/app/queryClient';
import { routes } from '@/app/routes';

function Boom(): never {
  throw new Error('boom');
}

describe('errorElement на корневом маршруте', () => {
  it('корень маршрутов объявляет errorElement', () => {
    expect(routes[0].errorElement).toBeDefined();
  });

  it('исключение при отрисовке экрана — понятная страница с «Обновить» и «На главную», а не белый экран', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const [root] = routes;
    const router = createMemoryRouter(
      [{ errorElement: root.errorElement, children: [...(root.children ?? []), { path: '/boom', element: <Boom /> }] }],
      { initialEntries: ['/boom'] },
    );
    render(<App router={router} queryClient={createQueryClient()} />);

    expect(await screen.findByRole('heading', { level: 1, name: 'Что-то пошло не так' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'На главную' })).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
