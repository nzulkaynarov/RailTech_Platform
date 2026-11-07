import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import * as fixtures from '@/mocks/fixtures';
import { portalServer } from '@/mocks/server';
import { renderApp, signedIn } from '@/test/render';
import { expectNoAxeViolations, heading } from '@/test/screens';

describe('Wave J7 & J2-audit: Статус отношений, архив документов и журнал безопасности', () => {
  describe('Документы: диапазон дат и экспорт реестра (J7)', () => {
    it('отображает контролы дат, фильтрует и экспортирует реестр CSV', async () => {
      signedIn();
      const user = userEvent.setup();
      renderApp('/documents');
      await heading('Документы');

      const list = await screen.findByRole('list', { name: 'Документы' });
      expect(within(list).getAllByRole('listitem')).toHaveLength(9);

      // Кнопка экспорта реестра видна
      const exportBtn = await screen.findByRole('button', { name: 'Экспорт реестра' });
      expect(exportBtn).toBeInTheDocument();

      // Вводим дату "С даты"
      const dateFromInput = screen.getByLabelText('С даты:');
      await user.type(dateFromInput, '01102026'); // 01.10.2026

      // Нажимаем экспорт реестра
      await user.click(await screen.findByRole('button', { name: 'Экспорт реестра' }));
      await waitFor(() => {
        expect(window.URL.createObjectURL).toHaveBeenCalled();
      });

      // Кнопка сброса дат появляется и очищает поля
      const resetBtn = await screen.findByRole('button', { name: 'Сбросить' });
      await user.click(resetBtn);
      expect(screen.queryByRole('button', { name: 'Сбросить' })).not.toBeInTheDocument();

      await expectNoAxeViolations();
    });
  });

  describe('Компания: статус отношений (J7) и журнал безопасности (J2-audit)', () => {
    it('отображает статус отношений и журнал безопасности для администратора', async () => {
      signedIn();
      renderApp('/company');
      await heading('Компания');

      // Статус отношений в профиле
      expect(await screen.findByText('Статус отношений')).toBeInTheDocument();
      expect(screen.getByText('Отношения активны')).toBeInTheDocument();

      // Журнал безопасности компании виден администратору
      expect(await screen.findByText('Журнал безопасности компании')).toBeInTheDocument();
      const secList = await screen.findByRole('list', { name: 'Журнал безопасности компании' });
      expect(within(secList).getAllByRole('listitem').length).toBeGreaterThan(0);
      expect(within(secList).getByText('Вход')).toBeInTheDocument();

      await expectNoAxeViolations();
    });

    it('показывает баннер приостановки отношений при статусе suspended', async () => {
      portalServer.use(
        http.get('*/api/portal/v1/company', () => {
          return HttpResponse.json({
            ...fixtures.company,
            relationship_status: 'suspended',
            relationships: [
              {
                role: 'client',
                status: 'suspended',
                contract_number: 'CTR-2026-SUSP',
                contract_date: '2026-01-10',
                activated_at: null,
                suspended_at: '2026-11-01T10:00:00Z',
              },
            ],
          });
        }),
      );

      signedIn();
      renderApp('/company');
      await heading('Компания');

      expect(
        await screen.findByText('Отношения временно приостановлены. Доступ открыт в режиме чтения архива.'),
      ).toBeInTheDocument();
      expect(screen.getByText('Приостановлены')).toBeInTheDocument();

      await expectNoAxeViolations();
    });

    it('показывает баннер завершения отношений при статусе terminated', async () => {
      portalServer.use(
        http.get('*/api/portal/v1/company', () => {
          return HttpResponse.json({
            ...fixtures.company,
            relationship_status: 'terminated',
            relationships: [
              {
                role: 'client',
                status: 'terminated',
                contract_number: 'CTR-2026-TERM',
                contract_date: '2026-01-10',
                activated_at: null,
                suspended_at: null,
              },
            ],
          });
        }),
      );

      signedIn();
      renderApp('/company');
      await heading('Компания');

      expect(
        await screen.findByText('Отношения завершены. Архив документов доступен для просмотра и выгрузки.'),
      ).toBeInTheDocument();
      expect(screen.getByText('Завершены')).toBeInTheDocument();

      await expectNoAxeViolations();
    });
  });
});
