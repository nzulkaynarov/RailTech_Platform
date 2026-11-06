import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';
import { ONBOARDING_DISMISSED_KEY } from '@/onboarding/checklistState';

const PARTNER_ACCESS = {
  roles: ['partner' as const],
  modules: ['my_products', 'catalog_requests', 'profile'],
};

describe('чек-лист «Первые шаги» и расширенный виджет «Требует вашего решения» (волна J1)', () => {
  beforeEach(() => {
    try {
      localStorage.removeItem(ONBOARDING_DISMISSED_KEY);
    } catch {
      // ignore
    }
  });

  describe('чек-лист «Первые шаги»', () => {
    it('отображает шаги онбординга для клиента и рассчитывает прогресс по данным портала', async () => {
      signedIn('actor', 'demo');
      renderApp('/requests');
      await heading('Запросы');

      expect(screen.getByText('Первые шаги в кабинете')).toBeInTheDocument();
      expect(screen.getByText('Реквизиты компании')).toBeInTheDocument();
      expect(screen.getByText('Уведомления в Telegram')).toBeInTheDocument();
      expect(screen.getByText('Создать первый запрос')).toBeInTheDocument();
      expect(screen.getByText('Пригласить коллег')).toBeInTheDocument();

      await expectNoAxeViolations();
    });

    it('позволяет скрыть чек-лист по кнопке закрытия', async () => {
      signedIn('actor', 'demo');
      const user = userEvent.setup();
      renderApp('/requests');
      await heading('Запросы');

      const dismissBtn = screen.getByRole('button', { name: 'Скрыть' });
      await user.click(dismissBtn);

      expect(screen.queryByText('Первые шаги в кабинете')).not.toBeInTheDocument();
      expect(localStorage.getItem(ONBOARDING_DISMISSED_KEY)).toBe('true');
    });

    it('для кандидата в партнёры показывает шаг согласования договора', async () => {
      signedIn('actor', 'empty');
      portalServer.use(
        http.get('*/api/portal/v1/company/partner-application', () =>
          HttpResponse.json({
            already_partner: false,
            has_application: true,
            application: {
              id: 99,
              status: 'contract_sent',
              kind: 'supplier',
              categories_description: 'Клапаны',
              contact_name: 'Тест',
              phone: '+998901234567',
              email: 'partner@test.uz',
              comment: '',
              contract_draft_url: '/contract.pdf',
              created_at: '2026-11-06T10:00:00Z',
              decided_at: null,
              rejection_reason: null,
            },
          }),
        ),
      );

      renderApp('/requests');
      await heading('Запросы');

      expect(await screen.findByText('Проект договора')).toBeInTheDocument();
    });
  });

  describe('виджет «Требует вашего решения» (J1)', () => {
    it('включает поставку со статусом delivered, ожидающую приёмки', async () => {
      signedIn('actor', 'demo');
      renderApp('/requests');
      await heading('Запросы');

      const region = await screen.findByRole('region', { name: 'Требует вашего решения' });
      expect(within(region).getByRole('link', { name: 'Редуктор червячный NMRV 063' })).toHaveAttribute(
        'href',
        '/deliveries',
      );
      expect(within(region).getByText('Поставка')).toBeInTheDocument();
    });

    it('включает проект партнёрского договора к согласованию при статусе contract_sent', async () => {
      signedIn('actor', 'empty');
      portalServer.use(
        http.get('*/api/portal/v1/company/partner-application', () =>
          HttpResponse.json({
            already_partner: false,
            has_application: true,
            application: {
              id: 99,
              status: 'contract_sent',
              kind: 'supplier',
              categories_description: 'Клапаны',
              contact_name: 'Тест',
              phone: '+998901234567',
              email: 'partner@test.uz',
              comment: '',
              contract_draft_url: '/contract.pdf',
              created_at: '2026-11-06T10:00:00Z',
              decided_at: null,
              rejection_reason: null,
            },
          }),
        ),
      );

      renderApp('/requests');
      await heading('Запросы');

      const region = await screen.findByRole('region', { name: 'Требует вашего решения' });
      expect(within(region).getByRole('link', { name: 'Проект партнёрского договора' })).toHaveAttribute(
        'href',
        '/company',
      );
      expect(within(region).getByText('Согласовать условия')).toBeInTheDocument();
    });

    it('включает товары партнёра с замечаниями снабжения (returned)', async () => {
      signedIn('actor', 'demo', PARTNER_ACCESS);
      portalServer.use(
        http.get('*/api/portal/v1/partner/products', ({ request }) => {
          const url = new URL(request.url);
          if (url.searchParams.get('status') === 'returned') {
            return HttpResponse.json({
              items: [
                {
                  id: 501,
                  name: 'Клапан предохранительный 17с28нж',
                  manufacturer_part_number: 'V-17S',
                  status: 'returned',
                  return_reason: 'Уточните рабочее давление',
                  brand: 'Тест',
                  category: 'Арматура',
                  can_submit: true,
                  offer: null,
                  completeness: { score: 80, missing: [] },
                  created_at: '2026-11-06T10:00:00Z',
                  updated_at: '2026-11-06T11:00:00Z',
                },
              ],
              total: 1,
              page: 1,
              page_size: 20,
            });
          }
          return HttpResponse.json({
            items: [],
            total: 0,
            counts: { all: 0, draft: 0, review: 0, published: 0, returned: 1, matched: 0 },
            attention: { stale: 0, expiring: 0, expired: 0 },
            page: 1,
            page_size: 20,
          });
        }),
      );

      renderApp('/my-products');
      await heading('Мои товары');

      const region = await screen.findByRole('region', { name: 'Требует вашего решения' });
      expect(within(region).getByRole('link', { name: 'Клапан предохранительный 17с28нж' })).toHaveAttribute(
        'href',
        '/my-products?tab=returned',
      );
      expect(within(region).getByText('Исправить замечания')).toBeInTheDocument();
    });
  });
});
