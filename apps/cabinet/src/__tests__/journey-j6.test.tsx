import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import * as fixtures from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { heading } from '@/test/screens';

describe('Wave J6 & B-CABFIX-2: Поиск, фильтры, повтор запроса в 1 клик и исход закрытия', () => {
  describe('Фильтры и поиск по запросам (J6)', () => {
    it('фильтрация по статусу переключает query param и фильтрует список', async () => {
      signedIn();
      const user = userEvent.setup();
      const { router } = renderApp('/requests');
      await heading('Запросы');

      const list = await screen.findByRole('list', { name: 'Запросы' });
      expect(within(list).getAllByRole('listitem')).toHaveLength(5);

      // Кликаем по фильтру «Закрыт»
      const closedFilter = screen.getByRole('button', { name: 'Закрыт' });
      await user.click(closedFilter);

      expect(router.state.location.search).toBe('?status=closed');
      await waitFor(() => {
        const items = within(list).getAllByRole('listitem');
        expect(items).toHaveLength(1);
        expect(items[0]).toHaveTextContent('ПР-2026-035');
      });

      // Сбрасываем фильтр кнопкой «Все»
      const allFilter = screen.getByRole('button', { name: 'Все' });
      await user.click(allFilter);
      expect(router.state.location.search).toBe('');
      await waitFor(() => {
        expect(within(list).getAllByRole('listitem')).toHaveLength(5);
      });
    });

    it('поиск по тексту фильтрует запросы на клиенте и через API', async () => {
      signedIn();
      const user = userEvent.setup();
      renderApp('/requests');
      await heading('Запросы');

      const searchInput = screen.getByRole('searchbox', { name: 'Поиск по номеру, описанию или позиции...' });
      await user.type(searchInput, 'Перчатки');

      const list = await screen.findByRole('list', { name: 'Запросы' });
      await waitFor(() => {
        const items = within(list).getAllByRole('listitem');
        expect(items).toHaveLength(1);
        expect(items[0]).toHaveTextContent('ЗВ-2026-061');
        expect(items[0]).toHaveTextContent('Перчатки нитриловые');
      });
    });

    it('при отсутствии совпадений показывается пустое состояние с кнопкой сброса поиска', async () => {
      signedIn();
      const user = userEvent.setup();
      renderApp('/requests');
      await heading('Запросы');

      const searchInput = screen.getByRole('searchbox', { name: 'Поиск по номеру, описанию или позиции...' });
      await user.type(searchInput, 'несуществующий артикул 99999');

      expect(await screen.findByText('Ничего не нашлось')).toBeInTheDocument();
      expect(screen.getByText('По запросу «несуществующий артикул 99999» запросов не найдено')).toBeInTheDocument();

      const clearBtn = screen.getByRole('button', { name: 'Сбросить поиск' });
      await user.click(clearBtn);

      const list = await screen.findByRole('list', { name: 'Запросы' });
      await waitFor(() => {
        expect(within(list).getAllByRole('listitem')).toHaveLength(5);
      });
    });
  });

  describe('Повтор запроса в 1 клик (J6)', () => {
    it('кнопка повтора в списке запросов открывает форму нового запроса с предзаполнением', async () => {
      signedIn();
      const user = userEvent.setup();
      const { router } = renderApp('/requests');
      await heading('Запросы');
      await screen.findByRole('list', { name: 'Запросы' });

      // Находим кнопку повтора у первого запроса
      const reorderBtns = await screen.findAllByRole('link', { name: /Повторить запрос/ });
      expect(reorderBtns.length).toBeGreaterThan(0);
      await user.click(reorderBtns[0]);

      expect(await heading('Новый запрос')).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/requests/new');

      const summaryInput = screen.getByLabelText('Что нужно') as HTMLTextAreaElement;
      expect(summaryInput.value).toContain('Повтор запроса');
    }, 60_000);

    it('кнопка повтора на детальной странице запроса предзаполняет форму', async () => {
      signedIn();
      const user = userEvent.setup();
      const { router } = renderApp('/requests/501');
      await heading('Запрос ЗВ-2026-042');

      const reorderBtn = screen.getByRole('link', { name: 'Повторить запрос' });
      await user.click(reorderBtn);

      expect(await heading('Новый запрос')).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/requests/new');
      expect(screen.getByLabelText('Что нужно')).toHaveValue('Повтор запроса ЗВ-2026-042: Подшипники 6205-2RS — 200 шт., ремни приводные SPZ 1250 — 40 шт.');
    }, 60_000);

    it('кнопка «Повторить проект» на странице сделки предзаполняет позиции из поставки', async () => {
      signedIn();
      const user = userEvent.setup();
      const { router } = renderApp('/deals/35');
      await heading('Проект ПР-2026-035');

      const reorderDealBtn = screen.getByRole('link', { name: 'Повторить проект' });
      await user.click(reorderDealBtn);

      expect(await heading('Новый запрос')).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/requests/new');
      expect(screen.getByLabelText('Что нужно')).toHaveValue('Повтор запроса ПР-2026-035: Редукторы и муфты');
    }, 60_000);
  });

  describe('Исход закрытого запроса / сделки (B-CABFIX-2)', () => {
    it('закрытый запрос с outcome=won отображает статус «Исполнен» в списке и в карточке', async () => {
      signedIn();
      const { router } = renderApp('/requests');
      await heading('Запросы');

      const list = await screen.findByRole('list', { name: 'Запросы' });
      // Запрос 504 закрыт с outcome: 'won'
      const item504 = within(list).getByText('ПР-2026-035').closest('li')!;
      expect(within(item504).getByText('Исполнен')).toBeInTheDocument();

      // Открываем детальную страницу
      await router.navigate('/requests/504');
      await heading('Запрос ПР-2026-035');
      expect(screen.getByText('Исполнен')).toBeInTheDocument();
    });

    it('закрытый запрос с outcome=cancelled отображает статус «Отменён»', async () => {
      signedIn();
      const cancelledReq = {
        ...fixtures.requests[4],
        id: 599,
        number: 'ЗВ-2026-099',
        status: 'closed' as const,
        outcome: 'cancelled' as const,
      };
      portalServer.use(
        http.get('*/api/portal/v1/requests/599', () => HttpResponse.json(cancelledReq)),
      );

      renderApp('/requests/599');
      await heading('Запрос ЗВ-2026-099');
      expect(screen.getByText('Отменён')).toBeInTheDocument();
    });
  });
});
