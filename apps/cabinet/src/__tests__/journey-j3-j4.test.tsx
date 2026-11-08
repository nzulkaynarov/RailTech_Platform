import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderApp, signedIn } from '@/test/render';
import { heading } from '@/test/screens';

describe('Wave J3, J4 & J2-bank Journey Tests', () => {
  describe('Wave J3: Матрица каналов уведомлений в Профиле', () => {
    it('отображает группы уведомлений, статус Telegram и защищённую группу безопасности', async () => {
      signedIn('actor');
      renderApp('/profile');

      await heading('Профиль');
      const matrix = document.getElementById('notification-settings-matrix')!;
      expect(matrix).toBeInTheDocument();

      // Дожидаемся загрузки данных настроек
      await within(matrix).findByText('Документы');

      // Проверяем наличие всех категорий внутри матрицы
      expect(within(matrix).getByText('Документы')).toBeInTheDocument();
      expect(within(matrix).getByText('Финансы')).toBeInTheDocument();
      expect(within(matrix).getByText('Доставки')).toBeInTheDocument();
      expect(within(matrix).getByText('Сообщения')).toBeInTheDocument();
      expect(within(matrix).getByText('Безопасность')).toBeInTheDocument();

      // Группа «Безопасность» обязательна
      expect(within(matrix).getByText('Обязательно')).toBeInTheDocument();

      // Чекбокс безопасности отключен для редактирования (disabled)
      const securityTelegramCheckbox = within(matrix).getByRole('checkbox', {
        name: 'Безопасность — Telegram',
      });
      expect(securityTelegramCheckbox).toBeDisabled();

      // Чекбокс документов доступен для переключения
      const docsEmailCheckbox = within(matrix).getByRole('checkbox', {
        name: 'Документы — E-mail',
      });
      expect(docsEmailCheckbox).not.toBeDisabled();
    });

    it('позволяет переключать каналы и сохраняет настройки', async () => {
      signedIn('actor');
      const user = userEvent.setup();
      renderApp('/profile');

      await heading('Профиль');
      const matrix = document.getElementById('notification-settings-matrix')!;
      await within(matrix).findByText('Документы');

      const docsEmailCheckbox = within(matrix).getByRole('checkbox', {
        name: 'Документы — E-mail',
      });
      expect(docsEmailCheckbox).toBeChecked();

      await user.click(docsEmailCheckbox);
      await waitFor(() => {
        expect(docsEmailCheckbox).not.toBeChecked();
      });
    });
  });

  describe('Wave J4: Контекстная справка (HelpDrawer)', () => {
    it('кнопка справки в шапке открывает шторку с актуальными статьями и поиском', async () => {
      signedIn('actor');
      const user = userEvent.setup();
      const { router } = renderApp('/quotes');

      await heading('Коммерческие предложения');

      const helpButton = screen.getByRole('button', { name: 'Справка и подсказки' });
      expect(helpButton).toBeInTheDocument();

      await user.click(helpButton);

      // Открылась шторка базы знаний
      const drawer = await screen.findByRole('dialog');
      expect(within(drawer).getByText('База знаний кабинета')).toBeInTheDocument();
      expect(within(drawer).getByText('Подсказки для этого раздела')).toBeInTheDocument();

      // Соответствующая статья для роута /quotes
      expect(
        within(drawer).getByText(/Как согласовать или отклонить коммерческое предложение/),
      ).toBeInTheDocument();

      // Поиск фильтрует статьи
      const searchInput = within(drawer).getByPlaceholderText('Поиск по статьям и инструкциям…');
      await user.type(searchInput, 'Telegram');

      expect(within(drawer).getByText(/Каналы уведомлений и привязка Telegram/)).toBeInTheDocument();

      // Кнопка обращения к менеджеру переходит в /messages
      const contactBtn = within(drawer).getByRole('button', { name: 'Написать персональному менеджеру' });
      await user.click(contactBtn);

      await waitFor(() => {
        expect(router.state.location.pathname).toBe('/messages');
      });
    });
  });

  describe('Wave J2-bank: Защита банковских реквизитов', () => {
    it('для пользователя без роли администратора редактирование банковских реквизитов заблокировано', async () => {
      signedIn('viewer'); // viewer has is_admin = false, language = uz
      renderApp('/company');

      await heading(/Компания|Kompaniya/);

      // В карточке отображается бейдж защиты (на языке контакта viewer — uz)
      expect(
        await screen.findByText(/Редактировать может только администратор|Faqat administrator/),
      ).toBeInTheDocument();
    });

    it('для администратора отображается предупреждение о безопасности при редактировании', async () => {
      signedIn('actor'); // actor has is_admin = true
      const user = userEvent.setup();
      renderApp('/company');

      await heading('Компания');

      const editBtn = await screen.findByRole('button', { name: 'Изменить' });
      await user.click(editBtn);

      // В форме редактирования реквизиты активны и видна подсказка о безопасности
      const bankTextarea = screen.getByLabelText('Банковские реквизиты');
      expect(bankTextarea).not.toBeDisabled();
      expect(
        screen.getByText(/применятся только после проверки сотрудником/),
      ).toBeInTheDocument();
    });
  });
});
